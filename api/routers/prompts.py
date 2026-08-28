"""
Prompt management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import math

from api.database import get_db
from api.dependencies import verify_api_key
from api.services.prompt_service import PromptService
from api.schemas.prompt import (
    PromptResponse,
    PromptUpdateRequest,
    PromptUpdateResponse,
    PromptHistoryResponse,
    PromptVersionResponse,
    PromptActivateResponse,
    DefaultPromptResponse,
    PromptVersionSummary,
    PaginationInfo,
)
from logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/prompts", tags=["Prompts"])


@router.get("/extraction", response_model=PromptResponse)
async def get_active_extraction_prompt(
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Get the current active extraction prompt.

    Returns:
        The active extraction prompt with version info
    """
    logger.info("Retrieving active extraction prompt")

    try:
        try:
            prompt = await PromptService.get_active_prompt(db)
        except Exception as e:
            logger.error(f"Database error retrieving active prompt: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve active prompt. Please try again.",
            )

        if not prompt:
            logger.info("No active prompt found, returning default prompt information")
            # Load default prompt
            from prompts.new_simplified_entity_extraction_prompt import (
                SIMPLIFIED_ENTITY_EXTRACTION_PROMPT,
            )

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "no_active_prompt",
                    "message": "No active extraction prompt configured. Using default prompt.",
                    "default_prompt_preview": SIMPLIFIED_ENTITY_EXTRACTION_PROMPT[:200]
                    + "...",
                },
            )

        logger.info(f"Retrieved active prompt version {prompt.version}")

        return PromptResponse(
            id=prompt.id,
            version=prompt.version,
            prompt_name=prompt.prompt_name,
            prompt_content=prompt.prompt_content,
            is_active=prompt.is_active,
            created_at=prompt.created_at,
            created_by=prompt.created_by,
            change_notes=prompt.change_notes,
            character_count=len(prompt.prompt_content),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_active_extraction_prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )


@router.put("/extraction", response_model=PromptUpdateResponse, status_code=status.HTTP_201_CREATED)
async def update_extraction_prompt(
    request: PromptUpdateRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Update the extraction prompt (creates new version).

    This is the ONLY prompt the client can modify.

    Args:
        request: Prompt update request with content and notes

    Returns:
        The newly created prompt version
    """
    logger.info(f"Updating extraction prompt (activate={request.activate_immediately})")

    try:
        try:
            new_prompt, previous_version = await PromptService.create_new_version(
                db=db,
                prompt_content=request.prompt_content,
                change_notes=request.change_notes,
                created_by=f"api_key:{api_key[:10]}",
                activate=request.activate_immediately,
            )

            logger.info(
                f"Created new prompt version {new_prompt.version} (previous: {previous_version})"
            )

            return PromptUpdateResponse(
                id=new_prompt.id,
                version=new_prompt.version,
                prompt_name=new_prompt.prompt_name,
                is_active=new_prompt.is_active,
                created_at=new_prompt.created_at,
                message="New prompt version created and activated"
                if request.activate_immediately
                else "New prompt version created (not activated)",
                previous_version=previous_version,
                character_count=len(new_prompt.prompt_content),
            )

        except ValueError as e:
            logger.warning(f"Validation error updating prompt: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "validation_error", "message": str(e)},
            )
        except Exception as e:
            logger.error(f"Database error creating new prompt version: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create new prompt version. Please try again.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in update_extraction_prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )


@router.get("/extraction/history", response_model=PromptHistoryResponse)
async def get_prompt_history(
    page: int = 1,
    per_page: int = 10,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Get prompt version history with pagination.

    Args:
        page: Page number (1-indexed)
        per_page: Items per page (max 50)

    Returns:
        List of prompt versions with pagination info
    """
    logger.info(f"Retrieving prompt history (page={page}, per_page={per_page})")

    try:
        # Validate pagination
        if page < 1:
            page = 1
        if per_page > 50:
            per_page = 50

        try:
            prompts, total_count = await PromptService.get_prompt_history(db, page, per_page)
            logger.info(f"Retrieved {len(prompts)} prompts (total: {total_count})")
        except Exception as e:
            logger.error(f"Database error retrieving prompt history: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve prompt history. Please try again.",
            )

        # Convert to response format
        try:
            versions = [
                PromptVersionSummary(
                    id=p.id,
                    version=p.version,
                    is_active=p.is_active,
                    created_at=p.created_at,
                    created_by=p.created_by,
                    change_notes=p.change_notes,
                    content_preview=p.prompt_content[:100] + "..."
                    if len(p.prompt_content) > 100
                    else p.prompt_content,
                    character_count=len(p.prompt_content),
                )
                for p in prompts
            ]

            total_pages = math.ceil(total_count / per_page) if total_count > 0 else 1

            logger.info(f"Successfully built prompt history response with {len(versions)} versions")

            return PromptHistoryResponse(
                versions=versions,
                pagination=PaginationInfo(
                    page=page,
                    per_page=per_page,
                    total_items=total_count,
                    total_pages=total_pages,
                ),
            )
        except Exception as e:
            logger.error(f"Error building prompt history response: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to build response. Please try again.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_prompt_history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )


@router.get("/extraction/default", response_model=DefaultPromptResponse)
async def get_default_prompt(api_key: str = Depends(verify_api_key)):
    """
    Get the default (built-in) extraction prompt for reference.

    Returns:
        The default prompt content
    """
    logger.info("Retrieving default extraction prompt")

    try:
        from prompts.new_simplified_entity_extraction_prompt import (
            SIMPLIFIED_ENTITY_EXTRACTION_PROMPT,
        )

        logger.info(f"Successfully retrieved default prompt ({len(SIMPLIFIED_ENTITY_EXTRACTION_PROMPT)} characters)")

        return DefaultPromptResponse(
            prompt_name="Default Entity Extraction Prompt",
            prompt_content=SIMPLIFIED_ENTITY_EXTRACTION_PROMPT,
            description="The built-in default prompt used when no custom prompt is configured.",
            character_count=len(SIMPLIFIED_ENTITY_EXTRACTION_PROMPT),
        )

    except Exception as e:
        logger.error(f"Error retrieving default prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve default prompt. Please contact support.",
        )


@router.get("/extraction/{version}", response_model=PromptVersionResponse)
async def get_prompt_version(
    version: int,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Get a specific prompt version by version number.

    Args:
        version: Version number to retrieve

    Returns:
        Full prompt details for the specified version
    """
    logger.info(f"Retrieving prompt version {version}")

    try:
        try:
            prompt = await PromptService.get_prompt_by_version(db, version)
        except Exception as e:
            logger.error(f"Database error retrieving prompt version {version}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve prompt version. Please try again.",
            )

        if not prompt:
            logger.warning(f"Prompt version {version} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "version_not_found", "message": f"Prompt version {version} not found"},
            )

        logger.info(f"Successfully retrieved prompt version {version}")

        return PromptVersionResponse(
            id=prompt.id,
            version=prompt.version,
            prompt_name=prompt.prompt_name,
            prompt_content=prompt.prompt_content,
            is_active=prompt.is_active,
            created_at=prompt.created_at,
            created_by=prompt.created_by,
            change_notes=prompt.change_notes,
            character_count=len(prompt.prompt_content),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_prompt_version for version {version}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )


@router.post("/extraction/{version}/activate", response_model=PromptActivateResponse)
async def activate_prompt_version(
    version: int,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Activate a specific prompt version (deactivates current active version).

    Args:
        version: Version number to activate

    Returns:
        Activation confirmation with previous active version
    """
    logger.info(f"Activating prompt version {version}")

    try:
        try:
            prompt, previous_version = await PromptService.activate_version(db, version)

            logger.info(
                f"Activated prompt version {version} (previous: {previous_version})"
            )

            return PromptActivateResponse(
                id=prompt.id,
                version=prompt.version,
                is_active=prompt.is_active,
                message=f"Prompt version {version} is now active",
                previous_active_version=previous_version,
                activated_at=datetime.utcnow(),
            )

        except ValueError as e:
            logger.warning(f"Validation error activating version {version}: {e}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "version_not_found", "message": str(e)},
            )
        except Exception as e:
            logger.error(f"Database error activating prompt version {version}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to activate prompt version. Please try again.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in activate_prompt_version for version {version}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )
