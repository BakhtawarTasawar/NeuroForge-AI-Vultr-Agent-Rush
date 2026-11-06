import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from typing import Optional
from sqlalchemy import text
from app.db.database import Base, engine
from app.db.migrations import run_migrations
from app.api.routers import auth, users, projects, datasets, experiments, overview, agent_research

logger = logging.getLogger("neuroforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure SQLite database tables are created on startup
    Base.metadata.create_all(bind=engine)
    # Apply schema migrations safely
    run_migrations()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend control plane for NeuroForge AI autonomous scientific experimentation platform.",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Global unhandled exception handler to protect internal details
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled system error processing request to {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "We couldn't complete this scientific request. Please try again."},
    )


# Include Routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(datasets.router)
app.include_router(experiments.router)
app.include_router(overview.router)
app.include_router(agent_research.router)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    database: Optional[str] = None
    vultr_inference_configured: bool = False
    vultr_inference_model: Optional[str] = None


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    tags=["System"],
)
def get_health() -> HealthResponse:
    db_status = "healthy"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error(f"Database health check failed: {exc}")
        db_status = "unhealthy"

    vultr_configured = bool(settings.VULTR_INFERENCE_API_KEY and len(settings.VULTR_INFERENCE_API_KEY.strip()) > 0)

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.current_env,
        database=db_status,
        vultr_inference_configured=vultr_configured,
        vultr_inference_model=settings.VULTR_INFERENCE_MODEL,
    )


@app.get(
    "/",
    status_code=status.HTTP_200_OK,
    tags=["System"],
)
def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
    }
