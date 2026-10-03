"""
routers/dashboard.py — Dashboard and feedback endpoints

GET  /dashboard/stats   — aggregate pilot metrics
GET  /dashboard/recent  — most recent diagnosis records
POST /diagnose/feedback — thumbs up/down on a diagnosis

The dashboard.html page (field team only) reads these endpoints.
Stats and recent records need a staff login (Cognito admin pool, any role).
Feedback needs a farmer login and only works on the farmer's own diagnoses.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

import database
from auth_service import Farmer, current_farmer, require_staff
from schemas import DashboardStatsResponse, FeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])
staff_only = [Depends(require_staff())]


@router.get("/dashboard/stats", response_model=DashboardStatsResponse, summary="Pilot metrics",
            dependencies=staff_only)
async def dashboard_stats():
    """
    Aggregate statistics for the pilot dashboard:
    - total diagnoses, chats, voice sessions
    - disease breakdown (count per disease)
    - average confidence
    - model mode breakdown (tflite vs random)
    - languages used
    - helpful feedback percentage
    - last 7 days daily diagnosis count

    **Errors:**
    - 500 — database read error
    """
    try:
        stats = await database.get_dashboard_stats()
    except Exception as exc:
        logger.exception("Failed to read dashboard stats from DB")
        raise HTTPException(status_code=500, detail="Could not load dashboard stats.") from exc

    return DashboardStatsResponse(**stats)


@router.get("/dashboard/recent", summary="Recent diagnoses", dependencies=staff_only)
async def dashboard_recent(limit: int = Query(20, ge=1, le=100, description="Number of records to return")):
    """
    Returns the most recent diagnosis records (newest first).
    Used by the dashboard table.

    **Errors:**
    - 500 — database read error
    """
    try:
        return await database.get_recent_diagnoses(limit)
    except Exception as exc:
        logger.exception("Failed to read recent diagnoses from DB")
        raise HTTPException(status_code=500, detail="Could not load recent diagnoses.") from exc


@router.post("/diagnose/feedback", summary="Submit helpful/not-helpful feedback")
async def diagnose_feedback(request: FeedbackRequest, farmer: Farmer = Depends(current_farmer)):
    """
    Record whether the diagnosis was helpful.
    Called when the farmer taps 👍 or 👎 in the frontend.

    **Errors:**
    - 404 — diagnosis_id not found in the database
    - 500 — database write error
    """
    try:
        updated = await database.update_diagnosis_feedback(farmer.user_id, request.diagnosis_id, request.helpful)
    except Exception as exc:
        logger.exception("Failed to update feedback for diagnosis_id=%s", request.diagnosis_id)
        raise HTTPException(status_code=500, detail="Could not save feedback.") from exc

    if not updated:
        raise HTTPException(
            status_code=404,
            detail=f"Diagnosis ID {request.diagnosis_id} not found.",
        )

    return {"status": "ok", "diagnosis_id": request.diagnosis_id, "helpful": request.helpful}
