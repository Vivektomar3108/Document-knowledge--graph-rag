"""
Health check and configuration endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from api.dependencies import verify_api_key
from api.config import settings
from logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", dependencies=[Depends(verify_api_key)])
async def health_check():
    """
    Health check endpoint to verify API is running.

    Returns:
        Basic health status
    """
    logger.info("Health check requested")

    try:
        response = {
            "status": "healthy",
            "api_version": settings.API_VERSION,
            "service": settings.API_TITLE,
        }
        logger.info("Health check passed")
        return response

    except Exception as e:
        logger.error(f"Error in health check: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Health check failed. Please contact support.",
        )


@router.get("/config", dependencies=[Depends(verify_api_key)])
async def get_config():
    """
    Get API configuration (non-sensitive settings only).

    Returns:
        Public configuration settings
    """
    logger.info("Configuration requested")

    try:
        config = {
            "api_version": settings.API_VERSION,
            "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
            "max_files_per_request": settings.MAX_FILES_PER_REQUEST,
            "allowed_file_extensions": settings.ALLOWED_FILE_EXTENSIONS,
            "s3_presigned_url_expiry_seconds": settings.S3_PRESIGNED_URL_EXPIRY,
            "default_extraction_model": settings.DEFAULT_EXTRACTION_MODEL,
            "default_merging_model": settings.DEFAULT_MERGING_MODEL,
        }
        logger.info("Configuration retrieved successfully")
        return config

    except Exception as e:
        logger.error(f"Error retrieving configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration. Please contact support.",
        )
