"""
routers/diseases.py — GET /diseases

Returns the full treatment knowledge base from diseases.json.
The frontend loads this once on startup and uses it offline (no further API calls).
To add a new disease: edit diseases.json — no code change needed.
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter()

DISEASES_FILE = Path(__file__).resolve().parent.parent / "diseases.json"

# In-memory cache — diseases.json is read once at first request, then served from memory.
_cache: dict[str, Any] | None = None


def load_diseases() -> dict[str, Any]:
    """Load and cache diseases.json. Raises HTTPException 500 if file is missing or corrupt."""
    global _cache
    if _cache is not None:
        return _cache
    if not DISEASES_FILE.exists():
        logger.error("diseases.json not found at %s", DISEASES_FILE)
        raise HTTPException(
            status_code=500,
            detail="Disease knowledge base not found. Contact the system administrator.",
        )
    try:
        with open(DISEASES_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        logger.info("Loaded diseases.json (%d entries)", len(_cache))
        return _cache
    except json.JSONDecodeError as exc:
        logger.error("diseases.json is not valid JSON: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Disease knowledge base is corrupt. Contact the system administrator.",
        ) from exc


@router.get("/diseases", summary="Full treatment knowledge base")
def get_diseases():
    """
    Returns all disease entries from diseases.json.

    Response shape:
        {
            "count": 10,
            "diseases": [
                {
                    "name": "Blast",
                    "cause": "...",
                    "severity_levels": ["Low", "Medium", "High"],
                    "organic_treatment": "...",
                    "chemical_treatment": "...",
                    "precautions": "...",     // may be null
                    "refer_to_kvk": false
                },
                ...
            ]
        }

    The frontend loads this once and uses it for the offline disease reference tab.
    To add or edit a disease, update diseases.json — no code change required.
    """
    raw = load_diseases()
    return {
        "count": len(raw),
        "diseases": [{"name": name, **data} for name, data in raw.items()],
    }
