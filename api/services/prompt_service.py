"""
Service for managing extraction prompts.
"""

import hashlib
from typing import Optional, List, Tuple
from sqlalchemy import select, update, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from api.models.prompt import ExtractionPrompt
from logger import setup_logger

logger = setup_logger(__name__)


class PromptService:
    """Service for prompt CRUD operations."""

    @staticmethod
    def calculate_content_hash(content: str) -> str:
        """Calculate SHA256 hash of prompt content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    async def get_active_prompt(db: AsyncSession) -> Optional[ExtractionPrompt]:
        """Get the currently active extraction prompt."""
        try:
            logger.debug("Querying for active prompt")
            result = await db.execute(
                select(ExtractionPrompt).where(ExtractionPrompt.is_active == True)
            )
            prompt = result.scalar_one_or_none()
            if prompt:
                logger.debug(f"Found active prompt version {prompt.version}")
            else:
                logger.debug("No active prompt found")
            return prompt
        except Exception as e:
            logger.error(f"Error getting active prompt: {e}", exc_info=True)
            raise

    @staticmethod
    async def get_prompt_by_version(
        db: AsyncSession, version: int
    ) -> Optional[ExtractionPrompt]:
        """Get a specific prompt version."""
        try:
            logger.debug(f"Querying for prompt version {version}")
            result = await db.execute(
                select(ExtractionPrompt).where(ExtractionPrompt.version == version)
            )
            prompt = result.scalar_one_or_none()
            if prompt:
                logger.debug(f"Found prompt version {version}")
            else:
                logger.debug(f"Prompt version {version} not found")
            return prompt
        except Exception as e:
            logger.error(f"Error getting prompt version {version}: {e}", exc_info=True)
            raise

    @staticmethod
    async def get_prompt_by_id(db: AsyncSession, prompt_id: UUID) -> Optional[ExtractionPrompt]:
        """Get a prompt by ID."""
        try:
            logger.debug(f"Querying for prompt ID {prompt_id}")
            result = await db.execute(
                select(ExtractionPrompt).where(ExtractionPrompt.id == prompt_id)
            )
            prompt = result.scalar_one_or_none()
            if prompt:
                logger.debug(f"Found prompt with ID {prompt_id}")
            else:
                logger.debug(f"Prompt with ID {prompt_id} not found")
            return prompt
        except Exception as e:
            logger.error(f"Error getting prompt by ID {prompt_id}: {e}", exc_info=True)
            raise

    @staticmethod
    async def create_new_version(
        db: AsyncSession,
        prompt_content: str,
        change_notes: Optional[str] = None,
        created_by: Optional[str] = None,
        activate: bool = True,
    ) -> Tuple[ExtractionPrompt, Optional[int]]:
        """
        Create a new prompt version.

        Args:
            db: Database session
            prompt_content: The prompt content
            change_notes: Notes about the changes
            created_by: Who created this version
            activate: Whether to activate this version immediately

        Returns:
            Tuple of (new_prompt, previous_version)
        """
        try:
            logger.info(f"Creating new prompt version (activate={activate})")

            # Get current active prompt to check for duplicates
            try:
                current_active = await PromptService.get_active_prompt(db)
                previous_version = current_active.version if current_active else None
                logger.debug(f"Previous version: {previous_version}")
            except Exception as e:
                logger.error(f"Error getting current active prompt: {e}", exc_info=True)
                raise

            # Check if content is different
            new_hash = PromptService.calculate_content_hash(prompt_content)
            if current_active and current_active.content_hash == new_hash:
                logger.warning("Prompt content is identical to current active version")
                raise ValueError("Prompt content is identical to current active version")

            # Get next version number
            try:
                result = await db.execute(select(func.max(ExtractionPrompt.version)))
                max_version = result.scalar()
                next_version = (max_version or 0) + 1
                logger.debug(f"Next version number: {next_version}")
            except Exception as e:
                logger.error(f"Error calculating next version number: {e}", exc_info=True)
                raise

            # Deactivate current active prompt if activating new one
            if activate and current_active:
                try:
                    await db.execute(
                        update(ExtractionPrompt)
                        .where(ExtractionPrompt.is_active == True)
                        .values(is_active=False)
                    )
                    logger.debug(f"Deactivated previous version {previous_version}")
                except Exception as e:
                    logger.error(f"Error deactivating previous version: {e}", exc_info=True)
                    raise

            # Create new prompt
            try:
                new_prompt = ExtractionPrompt(
                    version=next_version,
                    prompt_name="Entity Extraction Prompt",
                    prompt_content=prompt_content,
                    content_hash=new_hash,
                    is_active=activate,
                    created_by=created_by,
                    change_notes=change_notes,
                )

                db.add(new_prompt)
                await db.commit()
                await db.refresh(new_prompt)

                logger.info(f"Created new prompt version {next_version}, active={activate}")
                return new_prompt, previous_version
            except Exception as e:
                logger.error(f"Error creating new prompt record: {e}", exc_info=True)
                raise

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating new prompt version: {e}", exc_info=True)
            raise

    @staticmethod
    async def activate_version(
        db: AsyncSession, version: int
    ) -> Tuple[ExtractionPrompt, Optional[int]]:
        """
        Activate a specific prompt version.

        Args:
            db: Database session
            version: Version number to activate

        Returns:
            Tuple of (activated_prompt, previous_active_version)

        Raises:
            ValueError: If version not found
        """
        try:
            logger.info(f"Activating prompt version {version}")

            # Get current active version
            try:
                current_active = await PromptService.get_active_prompt(db)
                previous_version = current_active.version if current_active else None
                logger.debug(f"Current active version: {previous_version}")
            except Exception as e:
                logger.error(f"Error getting current active version: {e}", exc_info=True)
                raise

            # Get target version
            try:
                target = await PromptService.get_prompt_by_version(db, version)
                if not target:
                    logger.warning(f"Prompt version {version} not found")
                    raise ValueError(f"Prompt version {version} not found")
            except ValueError:
                raise
            except Exception as e:
                logger.error(f"Error getting target version {version}: {e}", exc_info=True)
                raise

            # Deactivate current active
            if current_active:
                try:
                    await db.execute(
                        update(ExtractionPrompt)
                        .where(ExtractionPrompt.is_active == True)
                        .values(is_active=False)
                    )
                    logger.debug(f"Deactivated version {previous_version}")
                except Exception as e:
                    logger.error(f"Error deactivating current active version: {e}", exc_info=True)
                    raise

            # Activate target version
            try:
                await db.execute(
                    update(ExtractionPrompt)
                    .where(ExtractionPrompt.version == version)
                    .values(is_active=True)
                )

                await db.commit()
                await db.refresh(target)

                logger.info(f"Activated prompt version {version}")
                return target, previous_version
            except Exception as e:
                logger.error(f"Error activating version {version}: {e}", exc_info=True)
                raise

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error activating version {version}: {e}", exc_info=True)
            raise

    @staticmethod
    async def get_prompt_history(
        db: AsyncSession, page: int = 1, per_page: int = 10
    ) -> Tuple[List[ExtractionPrompt], int]:
        """
        Get prompt version history with pagination.

        Args:
            db: Database session
            page: Page number (1-indexed)
            per_page: Items per page

        Returns:
            Tuple of (prompts, total_count)
        """
        try:
            logger.debug(f"Getting prompt history (page={page}, per_page={per_page})")

            # Get total count
            try:
                count_result = await db.execute(select(func.count(ExtractionPrompt.id)))
                total_count = count_result.scalar()
                logger.debug(f"Total prompt count: {total_count}")
            except Exception as e:
                logger.error(f"Error getting total prompt count: {e}", exc_info=True)
                raise

            # Get paginated results
            try:
                offset = (page - 1) * per_page
                result = await db.execute(
                    select(ExtractionPrompt)
                    .order_by(desc(ExtractionPrompt.version))
                    .limit(per_page)
                    .offset(offset)
                )
                prompts = result.scalars().all()
                logger.debug(f"Retrieved {len(prompts)} prompts for page {page}")

                return list(prompts), total_count
            except Exception as e:
                logger.error(f"Error getting paginated prompts: {e}", exc_info=True)
                raise

        except Exception as e:
            logger.error(f"Unexpected error getting prompt history: {e}", exc_info=True)
            raise
