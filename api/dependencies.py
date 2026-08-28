"""
FastAPI dependencies for authentication and common operations.
"""

from fastapi import Header, HTTPException, status
from api.config import settings


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """
    Verify the API key from request header.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        The validated API key

    Raises:
        HTTPException: 401 if API key is missing or invalid
    """
    if x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key
