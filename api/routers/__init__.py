"""API routers for endpoints."""

from api.routers.pipeline import router as pipeline_router
from api.routers.prompts import router as prompts_router
from api.routers.health import router as health_router

__all__ = ["pipeline_router", "prompts_router", "health_router"]
