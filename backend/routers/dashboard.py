"""
routers/dashboard.py — Dashboard and feedback endpoints
Returns plain dicts (no response_model) to avoid OpenAPI schema issues.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
import database
from schemas import FeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats", summary="Pilot metrics")
async def dashboard_stats():
    try:
        return await database.get_dashboard_stats()
    except Exception as exc:
        logger.exception("Failed to read dashboard stats")
        raise HTTPException(status_code=500, detail="Could not load dashboard stats.") from exc


@router.get("/dashboard/recent", summary="Recent diagnoses")
async def dashboard_recent(limit: int = Query(20, ge=1, le=100)):
    try:
        return await database.get_recent_diagnoses(limit)
    except Exception as exc:
        logger.exception("Failed to read recent diagnoses")
        raise HTTPException(status_code=500, detail="Could not load recent diagnoses.") from exc


@router.post("/diagnose/feedback", summary="Submit helpful/not-helpful feedback")
async def diagnose_feedback(request: FeedbackRequest):
    try:
        updated = await database.update_diagnosis_feedback(request.diagnosis_id, request.helpful)
    except Exception as exc:
        logger.exception("Failed to update feedback for diagnosis_id=%s", request.diagnosis_id)
        raise HTTPException(status_code=500, detail="Could not save feedback.") from exc

    if not updated:
        raise HTTPException(status_code=404, detail=f"Diagnosis ID {request.diagnosis_id} not found.")

    return {"status": "ok", "diagnosis_id": request.diagnosis_id, "helpful": request.helpful}
