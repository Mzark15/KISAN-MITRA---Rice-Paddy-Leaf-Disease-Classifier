from fastapi import APIRouter, HTTPException, Query

import database
from schemas import DashboardStatsResponse, FeedbackRequest

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def dashboard_stats():
    stats = await database.get_dashboard_stats()
    return DashboardStatsResponse(**stats)


@router.get("/dashboard/recent")
async def dashboard_recent(limit: int = Query(20, ge=1, le=100)):
    return await database.get_recent_diagnoses(limit)


@router.post("/diagnose/feedback")
async def diagnose_feedback(request: FeedbackRequest):
    updated = await database.update_diagnosis_feedback(
        request.diagnosis_id, request.helpful
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Diagnosis record not found.")
    return {"status": "ok", "diagnosis_id": request.diagnosis_id, "helpful": request.helpful}
