from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal
from app.seed import seed_demo


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_seed:
        with SessionLocal() as db:
            seed_demo(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="基于 LangGraph 的企业智能客服与业务 Agent 系统",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health", tags=["系统"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/health/live", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def readiness(response: Response) -> dict[str, str]:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "error"}
    return {"status": "ok", "database": "ok"}
