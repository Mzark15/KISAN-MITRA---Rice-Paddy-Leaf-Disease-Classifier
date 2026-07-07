"""Async SQLite persistence for pilot dashboard."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

DB_PATH = os.environ.get("DB_PATH", "data/kisan_mitra.db")

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    disease TEXT NOT NULL,
    confidence REAL NOT NULL,
    model_mode TEXT NOT NULL,
    language TEXT,
    village TEXT,
    feedback INTEGER
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    language TEXT NOT NULL,
    message_count INTEGER NOT NULL,
    had_diagnosis_context INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    language TEXT NOT NULL,
    stt_success INTEGER NOT NULL,
    tts_success INTEGER NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()


async def insert_diagnosis(
    disease: str,
    confidence: float,
    model_mode: str,
    language: Optional[str] = None,
    village: Optional[str] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO diagnoses (timestamp, disease, confidence, model_mode, language, village, feedback)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (_now_iso(), disease, confidence, model_mode, language, village),
        )
        await db.commit()
        return cursor.lastrowid


async def update_diagnosis_feedback(diagnosis_id: int, helpful: bool) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE diagnoses SET feedback = ? WHERE id = ?",
            (1 if helpful else 0, diagnosis_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def insert_chat_session(
    language: str, message_count: int, had_diagnosis_context: bool
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO chat_sessions (timestamp, language, message_count, had_diagnosis_context)
            VALUES (?, ?, ?, ?)
            """,
            (_now_iso(), language, message_count, 1 if had_diagnosis_context else 0),
        )
        await db.commit()
        return cursor.lastrowid


async def insert_voice_session(
    language: str, stt_success: bool, tts_success: bool
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO voice_sessions (timestamp, language, stt_success, tts_success)
            VALUES (?, ?, ?, ?)
            """,
            (_now_iso(), language, 1 if stt_success else 0, 1 if tts_success else 0),
        )
        await db.commit()
        return cursor.lastrowid


async def get_dashboard_stats() -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        total_diagnoses = (
            await (await db.execute("SELECT COUNT(*) AS c FROM diagnoses")).fetchone()
        )["c"]

        disease_rows = await (
            await db.execute(
                "SELECT disease, COUNT(*) AS c FROM diagnoses GROUP BY disease"
            )
        ).fetchall()
        disease_breakdown = {row["disease"]: row["c"] for row in disease_rows}

        avg_row = await (
            await db.execute("SELECT AVG(confidence) AS avg_conf FROM diagnoses")
        ).fetchone()
        avg_confidence = round(avg_row["avg_conf"] or 0.0, 2)

        mode_rows = await (
            await db.execute(
                "SELECT model_mode, COUNT(*) AS c FROM diagnoses GROUP BY model_mode"
            )
        ).fetchall()
        model_mode_breakdown = {row["model_mode"]: row["c"] for row in mode_rows}

        total_chats = (
            await (await db.execute("SELECT COUNT(*) AS c FROM chat_sessions")).fetchone()
        )["c"]

        total_voice_sessions = (
            await (await db.execute("SELECT COUNT(*) AS c FROM voice_sessions")).fetchone()
        )["c"]

        lang_rows = await (
            await db.execute(
                """
                SELECT language, COUNT(*) AS c FROM diagnoses
                WHERE language IS NOT NULL AND language != ''
                GROUP BY language
                """
            )
        ).fetchall()
        languages_used = {row["language"]: row["c"] for row in lang_rows}

        feedback_row = await (
            await db.execute(
                """
                SELECT
                    SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS helpful,
                    SUM(CASE WHEN feedback IS NOT NULL THEN 1 ELSE 0 END) AS total
                FROM diagnoses
                """
            )
        ).fetchone()
        helpful_feedback_pct = 0.0
        if feedback_row["total"]:
            helpful_feedback_pct = round(
                100.0 * feedback_row["helpful"] / feedback_row["total"], 1
            )

        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=6)).date().isoformat()
        day_rows = await (
            await db.execute(
                """
                SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS c
                FROM diagnoses
                WHERE substr(timestamp, 1, 10) >= ?
                GROUP BY day
                ORDER BY day
                """,
                (seven_days_ago,),
            )
        ).fetchall()
        day_map = {row["day"]: row["c"] for row in day_rows}
        last_7_days_diagnoses = []
        for i in range(6, -1, -1):
            day = (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat()
            last_7_days_diagnoses.append({"date": day, "count": day_map.get(day, 0)})

        return {
            "total_diagnoses": total_diagnoses,
            "disease_breakdown": disease_breakdown,
            "avg_confidence": avg_confidence,
            "model_mode_breakdown": model_mode_breakdown,
            "total_chats": total_chats,
            "total_voice_sessions": total_voice_sessions,
            "languages_used": languages_used,
            "helpful_feedback_pct": helpful_feedback_pct,
            "last_7_days_diagnoses": last_7_days_diagnoses,
        }


async def get_recent_diagnoses(limit: int = 20) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (
            await db.execute(
                """
                SELECT id, timestamp, disease, confidence, language, village, feedback
                FROM diagnoses
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ).fetchall()
        return [dict(row) for row in rows]
