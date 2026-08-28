"""
Main FastAPI application for Borges Knowledge Graph API.

IMPORTANT: Run from the parent directory:
    cd ..
    python -m api.main

Or use uvicorn:
    cd ..
    uvicorn api.main:app --reload
"""

import sys
from pathlib import Path

# Add parent directory to sys.path if running from api/ directory
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from api.config import settings
from api.database import init_db
from api.routers import pipeline_router, prompts_router, health_router
from logger import setup_logger

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    """
    # Startup
    logger.info("Starting Borges Knowledge Graph API...")
    await init_db()
    logger.info("Database initialized")
    logger.info(f"API started successfully on {settings.API_PREFIX}")

    yield

    # Shutdown
    logger.info("Shutting down Borges Knowledge Graph API...")


# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="""
    API for running the Borges Knowledge Graph extraction pipeline.

    ## Features
    - Upload multiple PDF or XML files for processing
    - Monitor pipeline progress with detailed step visibility
    - Download final CSV outputs via presigned URLs
    - Manage and version the entity extraction prompt

    ## Authentication
    All endpoints require an API key provided via the `X-API-Key` header.
    """,
    lifespan=lifespan,
    docs_url=f"{settings.API_PREFIX}/docs",
    redoc_url=f"{settings.API_PREFIX}/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please contact support.",
        },
    )


# Include routers
app.include_router(pipeline_router, prefix=settings.API_PREFIX)
app.include_router(prompts_router, prefix=settings.API_PREFIX)
app.include_router(health_router, prefix=settings.API_PREFIX)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": settings.API_TITLE,
        "version": settings.API_VERSION,
        "docs": f"{settings.API_PREFIX}/docs",
        "health": f"{settings.API_PREFIX}/health",
    }


# Health check (no auth required)
@app.get(f"{settings.API_PREFIX}/ping")
async def ping():
    """Simple ping endpoint (no authentication required)."""
    return {"status": "ok", "message": "pong"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Enable auto-reload for development
        log_level="info",
    )
