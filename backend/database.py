"""
database.py — DynamoDB persistence (tables created by infra/ Terraform)

Tables (names are "<DYNAMODB_TABLE_PREFIX>-<table>", e.g. kisan-mitra-dev-users):
  users        — one item per farmer, keyed by Cognito user id (sub)
  diagnoses    — one item per /diagnose call; GSIs by_day and by_user
  stats        — dashboard counters, one item per day ("day#YYYY-MM-DD"),
                 updated atomically so the dashboard never scans diagnoses
  rate-limits  — OTP / login throttling counters, auto-expired via TTL

boto3 is synchronous; every public function is async and runs the call in a
worker thread so the event loop stays free.

Credentials come from the standard AWS chain: AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY env vars (local dev, from `terraform output backend_env`),
~/.aws, or the ECS task IAM role (production — no keys on the server).
"""

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

TABLE_PREFIX = os.environ.get("DYNAMODB_TABLE_PREFIX", "kisan-mitra-dev")
REGION = os.environ.get("AWS_REGION", "ap-south-1")

# How far back the dashboard's "recent diagnoses" list looks.
RECENT_LOOKBACK_DAYS = 30

_resource = None


def _dynamodb():
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb", region_name=REGION)
    return _resource


def _table(name: str):
    return _dynamodb().Table(f"{TABLE_PREFIX}-{name}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds")   # also the sort key for "recent" lists


def _dec(value: float) -> Decimal:
    """DynamoDB numbers must be Decimal, never float."""
    return Decimal(str(round(value, 2)))


def _plain(value: Any) -> Any:
    """Convert DynamoDB Decimals back to int/float for JSON responses."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

TABLES = ("users", "diagnoses", "stats", "rate-limits")


def _check_tables() -> list[str]:
    missing = []
    for name in TABLES:
        try:
            _table(name).load()
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                missing.append(f"{TABLE_PREFIX}-{name}")
            else:
                raise
    return missing


async def init_db() -> bool:
    """
    Check that every table exists. Called once at startup.

    Never raises: if AWS is unreachable the app still starts (so /health works
    and shows the problem) and data calls fail with a clear log message.
    """
    try:
        missing = await _run(_check_tables)
    except Exception as exc:
        logger.error("DynamoDB not reachable (%s). Check AWS credentials and region %s.", exc, REGION)
        return False
    if missing:
        logger.error("DynamoDB tables missing: %s. Run `terraform apply` in infra/.", missing)
        return False
    logger.info("DynamoDB ready: %s-* in %s", TABLE_PREFIX, REGION)
    return True


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _upsert_user(user_id: str, phone: str) -> dict[str, Any]:
    now = _iso(_now())
    resp = _table("users").update_item(
        Key={"user_id": user_id},
        UpdateExpression=(
            "SET phone = :phone, last_login_at = :now, "
            "created_at = if_not_exists(created_at, :now), "
            "#lang = if_not_exists(#lang, :lang)"
        ),
        ExpressionAttributeNames={"#lang": "language"},
        ExpressionAttributeValues={":phone": phone, ":now": now, ":lang": "hi"},
        ReturnValues="ALL_NEW",
    )
    return _plain(resp["Attributes"])


async def upsert_user(user_id: str, phone: str) -> dict[str, Any]:
    """Create the farmer on first login, or record the new login time."""
    return await _run(_upsert_user, user_id, phone)


async def get_user(user_id: str) -> Optional[dict[str, Any]]:
    resp = await _run(_table("users").get_item, Key={"user_id": user_id})
    item = resp.get("Item")
    return _plain(item) if item else None


def _update_profile(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    values[":now"] = _iso(_now())
    sets = ", ".join(f"#{k} = :{k}" for k in fields)
    resp = _table("users").update_item(
        Key={"user_id": user_id},
        UpdateExpression=f"SET {sets}, updated_at = :now",
        ConditionExpression="attribute_exists(user_id)",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return _plain(resp["Attributes"])


async def update_user_profile(user_id: str, **fields: Any) -> dict[str, Any]:
    """Update profile fields (language, village, name). None values are skipped."""
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return await get_user(user_id) or {}
    return await _run(_update_profile, user_id, fields)


def _delete_user_data(user_id: str) -> int:
    """Delete the profile and every diagnosis of a farmer. Dashboard counters stay (they are anonymous totals)."""
    table = _table("diagnoses")
    deleted = 0
    kwargs: dict[str, Any] = {
        "IndexName": "by_user",
        "KeyConditionExpression": Key("user_id").eq(user_id),
        "ProjectionExpression": "diagnosis_id",
    }
    with table.batch_writer() as batch:
        while True:
            resp = table.query(**kwargs)
            for item in resp["Items"]:
                batch.delete_item(Key={"diagnosis_id": item["diagnosis_id"]})
                deleted += 1
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    _table("users").delete_item(Key={"user_id": user_id})
    return deleted


async def delete_user_data(user_id: str) -> int:
    """Account deletion (Play Store requirement). Returns the number of diagnoses removed."""
    return await _run(_delete_user_data, user_id)


# ---------------------------------------------------------------------------
# Stats counters
# ---------------------------------------------------------------------------

def _bump_stats(day: str, counters: dict[str, Any]) -> None:
    """Atomically add to counters on the day's stats item (created on first use)."""
    names, values, adds = {}, {}, []
    for i, (field, amount) in enumerate(counters.items()):
        names[f"#f{i}"] = field
        values[f":v{i}"] = amount
        adds.append(f"#f{i} :v{i}")
    _table("stats").update_item(
        Key={"pk": f"day#{day}"},
        UpdateExpression="ADD " + ", ".join(adds),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


# ---------------------------------------------------------------------------
# Diagnoses
# ---------------------------------------------------------------------------

def _insert_diagnosis(user_id, disease, confidence, model_mode, language, village) -> str:
    now = _now()
    day = now.date().isoformat()
    diagnosis_id = uuid.uuid4().hex
    item = {
        "diagnosis_id": diagnosis_id,
        "user_id": user_id,
        "created_at": _iso(now),
        "day": day,
        "disease": disease,
        "confidence": _dec(confidence),
        "model_mode": model_mode,
    }
    if language:
        item["language"] = language
    if village:
        item["village"] = village
    _table("diagnoses").put_item(Item=item)

    counters = {
        "diagnoses": 1,
        "confidence_sum": _dec(confidence),
        f"disease:{disease}": 1,
        f"model:{model_mode}": 1,
    }
    if language:
        counters[f"lang:{language}"] = 1
    _bump_stats(day, counters)
    return diagnosis_id


async def insert_diagnosis(
    user_id: str,
    disease: str,
    confidence: float,
    model_mode: str,
    language: Optional[str] = None,
    village: Optional[str] = None,
) -> str:
    """Store a diagnosis and return its id (used for feedback)."""
    return await _run(_insert_diagnosis, user_id, disease, confidence, model_mode, language, village)


def _update_feedback(user_id: str, diagnosis_id: str, helpful: bool) -> bool:
    try:
        resp = _table("diagnoses").update_item(
            Key={"diagnosis_id": diagnosis_id},
            UpdateExpression="SET feedback = :fb, feedback_at = :now",
            # Only the farmer who made the diagnosis, and only once (keeps stats exact).
            ConditionExpression="user_id = :uid AND attribute_not_exists(feedback)",
            ExpressionAttributeValues={":fb": 1 if helpful else 0, ":uid": user_id, ":now": _iso(_now())},
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        existing = _table("diagnoses").get_item(Key={"diagnosis_id": diagnosis_id}).get("Item")
        # Already answered by this farmer: treat as success (idempotent).
        return bool(existing and existing.get("user_id") == user_id)

    _bump_stats(resp["Attributes"]["day"], {"feedback_total": 1, "feedback_helpful": 1 if helpful else 0})
    return True


async def update_diagnosis_feedback(user_id: str, diagnosis_id: str, helpful: bool) -> bool:
    """
    Record 👍/👎 on a diagnosis.
    Returns False if the diagnosis doesn't exist or belongs to another farmer.
    """
    return await _run(_update_feedback, user_id, diagnosis_id, helpful)


# ---------------------------------------------------------------------------
# Chat & voice sessions (counters only — no message content is stored)
# ---------------------------------------------------------------------------

async def insert_chat_session(language: str, message_count: int, had_diagnosis_context: bool) -> None:
    counters = {"chats": 1, "chat_messages": message_count, f"chat_lang:{language}": 1}
    if had_diagnosis_context:
        counters["chats_with_diagnosis"] = 1
    await _run(_bump_stats, _now().date().isoformat(), counters)


async def insert_voice_session(language: str, stt_success: bool, tts_success: bool) -> None:
    counters = {
        "voice": 1,
        "voice_stt_ok": 1 if stt_success else 0,
        "voice_tts_ok": 1 if tts_success else 0,
        f"voice_lang:{language}": 1,
    }
    await _run(_bump_stats, _now().date().isoformat(), counters)


# ---------------------------------------------------------------------------
# Rate limiting (fixed window, shared across all server instances)
# ---------------------------------------------------------------------------

def _hit(key: str, limit: int, window_seconds: int) -> bool:
    window = int(time.time()) // window_seconds
    resp = _table("rate-limits").update_item(
        Key={"pk": f"{key}#{window}"},
        UpdateExpression="ADD hits :one SET expires_at = if_not_exists(expires_at, :exp)",
        ExpressionAttributeValues={":one": 1, ":exp": (window + 1) * window_seconds + 60},
        ReturnValues="UPDATED_NEW",
    )
    return int(resp["Attributes"]["hits"]) <= limit


async def rate_limit_ok(key: str, limit: int, window_seconds: int) -> bool:
    """Count one hit for `key`; False once it exceeds `limit` in the current window."""
    return await _run(_hit, key, limit, window_seconds)


# ---------------------------------------------------------------------------
# Dashboard queries
# ---------------------------------------------------------------------------

def _all_stats_items() -> list[dict[str, Any]]:
    # The stats table holds one small item per day (~365 per year), so a scan is cheap.
    table = _table("stats")
    items, kwargs = [], {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return [_plain(i) for i in items]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _prefixed(totals: dict[str, float], prefix: str) -> dict[str, int]:
    return {k[len(prefix):]: int(v) for k, v in totals.items() if k.startswith(prefix) and v}


async def get_dashboard_stats() -> dict[str, Any]:
    """Aggregate pilot metrics from the per-day counter items."""
    items = await _run(_all_stats_items)

    totals: dict[str, float] = {}
    per_day: dict[str, int] = {}
    for item in items:
        per_day[item["pk"].removeprefix("day#")] = int(item.get("diagnoses", 0))
        for field, value in item.items():
            if field != "pk":
                totals[field] = totals.get(field, 0) + value

    diagnoses = int(totals.get("diagnoses", 0))
    feedback_total = totals.get("feedback_total", 0)
    today = _now().date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

    return {
        "total_diagnoses":       diagnoses,
        "disease_breakdown":     _prefixed(totals, "disease:"),
        "avg_confidence":        round(totals.get("confidence_sum", 0) / diagnoses, 2) if diagnoses else 0.0,
        "model_mode_breakdown":  _prefixed(totals, "model:"),
        "total_chats":           int(totals.get("chats", 0)),
        "total_voice_sessions":  int(totals.get("voice", 0)),
        "languages_used":        _prefixed(totals, "lang:"),
        "helpful_feedback_pct":  (
            round(100.0 * totals.get("feedback_helpful", 0) / feedback_total, 1) if feedback_total else 0.0
        ),
        "last_7_days_diagnoses": [{"date": d, "count": per_day.get(d, 0)} for d in days],
    }


def _recent(limit: int) -> list[dict[str, Any]]:
    table = _table("diagnoses")
    rows: list[dict[str, Any]] = []
    today = _now().date()
    for back in range(RECENT_LOOKBACK_DAYS):
        day = (today - timedelta(days=back)).isoformat()
        resp = table.query(
            IndexName="by_day",
            KeyConditionExpression=Key("day").eq(day),
            ScanIndexForward=False,   # newest first
            Limit=limit - len(rows),
        )
        rows.extend(resp["Items"])
        if len(rows) >= limit:
            break
    return [
        {
            "diagnosis_id": r["diagnosis_id"],
            "timestamp":    r["created_at"],
            "disease":      r["disease"],
            "confidence":   _plain(r["confidence"]),
            "language":     r.get("language"),
            "village":      r.get("village"),
            "feedback":     _plain(r.get("feedback")),
        }
        for r in rows
    ]


async def get_recent_diagnoses(limit: int = 20) -> list[dict[str, Any]]:
    """Most recent diagnoses across all farmers (newest first), for the dashboard."""
    return await _run(_recent, limit)
