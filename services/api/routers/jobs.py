from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import Engine

from services.api.dependencies import get_engine
from services.api.schemas.jobs import JobStatus
from services.api.services import audio as audio_service

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str, engine: Engine = Depends(get_engine)) -> dict:
    return audio_service.job_status(engine, job_id)
