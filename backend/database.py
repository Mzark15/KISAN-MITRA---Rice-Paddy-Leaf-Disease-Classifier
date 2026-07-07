"""
database.py — Async SQLite persistence for the pilot dashboard

Tables:
  diagnoses     — every /diagnose call (disease, confidence, feedback)
  chat_sessions — every /chat call (language, message count)
  voice_sessions — every /voice/chat call (STT/TTS success flags)

DB file location: controlled by DB_PATH env var (default: data/kisan_mitra.db).
Tables are created automatically on first run — no migration needed.

To add a new column: add it to the CREATE TABLE statement and to the relevant
insert/query function below. SQLite will create the column on next restart
if you use ALTER TABLE, or just delete the .db file in development.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

# Path to the SQLite file. Override with DB_PATH env var.
DB_PATH: str = os.environ.get("DB_PATH", "data/kisan_mitra.db")

_CREATE_TABLES = """\
CREATE TABLE IF NOT EXISTS diagnoses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    disease     TEXT    NOT NULL,
    confidence  REAL    NOT NULL,
    model_mode  TEXT    NOT NULL,   -- 'tflite' | 'random'
    language    TEXT,               -- 'hi' | 'mr' | 'en'
    village     TEXT,               -- optional farmer location
    feedback    INTEGER             -- NULL | 1 (helpful) | 0 (not helpful)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp             TEXT    NOT NULL,
    language              TEXT    NOT NULL,
    message_count         INTEGER NOT NULL,
    had_diagnosis_context INTEGER NOT NULL   -- 1 | 0
);

CREATE TABLE IF NOT EXISTS voice_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    language    TEXT    NOT NULL,
    stt_success INTEGER NOT NULL,   -- 1 | 0
    tts_success INTEGER NOT NULL    -- 1 | 0
);
"""


def _utcnow() -> str:
    """Current UTC time as ISO 8601 string (stored in all timestamp columns)."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """
    Create the database file and tables if they don't exist.
    Called once at startup. Safe to call on every restart.
    """
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()
    logger.info("Database initialised: %s", DB_PATH)


# ---------------------------------------------------------------------------
# Diagnoses
# ---------------------------------------------------------------------------

async def insert_diagnosis(
    disease: str,
    confidence: float,
    model_mode: str,
    language: Optional[str] = None,
    village: Optional[str] = None,
) -> int:
    """Insert a diagnosis record and return the new row ID (used for feedback)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO diagnoses
               (timestamp, disease, confidence, model_mode, language, village, feedback)
               VALUES (?, ?, ?, ?, ?, ?, NULL)""",
            (_utcnow(), disease, confidence, model_mode, language, village),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def update_diagnosis_feedback(diagnosis_id: int, helpful: bool) -> bool:
    """
    Set the feedback column for a diagnosis.
    Returns True if a row was updated, False if diagnosis_id not found.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE diagnoses SET feedback = ? WHERE id = ?",
            (1 if helpful else 0, diagnosis_id),
        )
        await db.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Chat & Voice sessions
# ---------------------------------------------------------------------------

async def insert_chat_session(
    language: str,
    message_count: int,
    had_diagnosis_context: bool,
) -> int:
    """Log a chat session. Called in a background task after each /chat response."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO chat_sessions
               (timestamp, language, message_count, had_diagnosis_context)
               VALUES (?, ?, ?, ?)""",
            (_utcnow(), language, message_count, 1 if had_diagnosis_context else 0),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def insert_voice_session(
    language: str,
    stt_success: bool,
    tts_success: bool,
) -> int:
    """Log a voice session. Called in a background task after each /voice/chat response."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO voice_sessions
               (timestamp, language, stt_success, tts_success)
               VALUES (?, ?, ?, ?)""",
            (_utcnow(), language, 1 if stt_success else 0, 1 if tts_success else 0),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Dashboard queries
# ---------------------------------------------------------------------------

async def get_dashboard_stats() -> dict[str, Any]:
    """
    Compute aggregate pilot metrics.
    All queries run in a single DB connection for efficiency.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Total counts
        total_diagnoses   = (await (await db.execute("SELECT COUNT(*) AS c FROM diagnoses")).fetchone())["c"]
        total_chats       = (await (await db.execute("SELECT COUNT(*) AS c FROM chat_sessions")).fetchone())["c"]
        total_voice       = (await (await db.execute("SELECT COUNT(*) AS c FROM voice_sessions")).fetchone())["c"]

        # Disease breakdown
        rows = await (await db.execute(
            "SELECT disease, COUNT(*) AS c FROM diagnoses GROUP BY disease"
        )).fetchall()
        disease_breakdown = {r["disease"]: r["c"] for r in rows}

        # Average confidence
        row = await (await db.execute("SELECT AVG(confidence) AS avg FROM diagnoses")).fetchone()
        avg_confidence = round(float(row["avg"] or 0.0), 2)

        # Model mode breakdown (tflite vs random)
        rows = await (await db.execute(
            "SELECT model_mode, COUNT(*) AS c FROM diagnoses GROUP BY model_mode"
        )).fetchall()
        model_mode_breakdown = {r["model_mode"]: r["c"] for r in rows}

        # Languages used (from diagnoses only — most representative)
        rows = await (await db.execute(
            "SELECT language, COUNT(*) AS c FROM diagnoses "
            "WHERE language IS NOT NULL AND language != '' GROUP BY language"
        )).fetchall()
        languages_used = {r["language"]: r["c"] for r in rows}

        # Feedback percentage
        row = await (await db.execute(
            """SELECT
                SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS helpful,
                SUM(CASE WHEN feedback IS NOT NULL THEN 1 ELSE 0 END) AS total
               FROM diagnoses"""
        )).fetchone()
        helpful_pct = (
            round(100.0 * float(row["helpful"]) / float(row["total"]), 1)
            if row["total"]
            else 0.0
        )

        # Last 7 days — one entry per day even if count = 0
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=6)).date().isoformat()
        rows = await (await db.execute(
            """SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS c
               FROM diagnoses
               WHERE substr(timestamp, 1, 10) >= ?
               GROUP BY day ORDER BY day""",
            (seven_days_ago,),
        )).fetchall()
        day_map = {r["day"]: r["c"] for r in rows}
        last_7_days = [
            {"date": (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat(),
             "count": day_map.get(
                 (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat(), 0
             )}
            for i in range(6, -1, -1)
        ]

    return {
        "total_diagnoses":       total_diagnoses,
        "disease_breakdown":     disease_breakdown,
        "avg_confidence":        avg_confidence,
        "model_mode_breakdown":  model_mode_breakdown,
        "total_chats":           total_chats,
        "total_voice_sessions":  total_voice,
        "languages_used":        languages_used,
        "helpful_feedback_pct":  helpful_pct,
        "last_7_days_diagnoses": last_7_days,
    }


async def get_recent_diagnoses(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent diagnosis records (newest first)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(
            """SELECT id, timestamp, disease, confidence, language, village, feedback
               FROM diagnoses ORDER BY id DESC LIMIT ?""",
            (limit,),
        )).fetchall()
    return [dict(r) for r in rows]
