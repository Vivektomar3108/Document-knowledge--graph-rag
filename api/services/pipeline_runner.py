"""
Pipeline runner service for executing the knowledge graph extraction pipeline.
All blocking I/O operations are wrapped with asyncio.to_thread() for non-blocking execution.
The entire pipeline runs in a thread pool to prevent blocking the FastAPI event loop.
"""

import asyncio
import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from api.models.pipeline import PipelineRun, InputFile, PipelineStatusUpdate
from api.services.s3_service import S3Service
from api.services.prompt_service import PromptService
from logger import setup_logger

logger = setup_logger(__name__)

# ── Ensure the project root is on sys.path so the root main.py's own
#     imports (pdf_utils, xml_utils, …) resolve correctly.
_ROOT_DIR = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

_ROOT_MAIN_CACHE_KEY = "_borges_root_main"


def _load_root_main():
    """
    Import the root-level main.py by absolute path.

    A plain ``from main import …`` resolves to api/main.py when the API
    is started from the api/ directory (or when uvicorn caches that module
    as ``main``).  Using importlib with an explicit file path avoids the
    ambiguity entirely.  The loaded module is cached in sys.modules so the
    top-level code in main.py only executes once.
    """
    if _ROOT_MAIN_CACHE_KEY in sys.modules:
        return sys.modules[_ROOT_MAIN_CACHE_KEY]

    root_main_path = Path(_ROOT_DIR) / "main.py"
    if not root_main_path.exists():
        raise ImportError(
            f"Root main.py not found at {root_main_path}. "
            "Ensure the API is deployed alongside the pipeline codebase."
        )

    spec = importlib.util.spec_from_file_location(_ROOT_MAIN_CACHE_KEY, str(root_main_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ROOT_MAIN_CACHE_KEY] = module
    spec.loader.exec_module(module)
    return module


class PipelineRunner:
    """Service for running the pipeline in the background."""

    def __init__(self, s3_service: S3Service):
        """
        Initialize pipeline runner.

        Args:
            s3_service: S3 service instance for file uploads
        """
        self.s3_service = s3_service

    async def run_pipeline(
        self,
        process_id: UUID,
        file_paths: list[str],
        file_type: str,
        db_url: str,
        temp_dir: str,
    ) -> None:
        """
        Run the complete pipeline as a background async task.
        
        All blocking I/O operations are wrapped with asyncio.to_thread() to prevent
        blocking the API event loop, allowing the API to handle other requests concurrently.

        This method orchestrates the entire pipeline:
        1. Text extraction from PDF/XML (async via thread pool)
        2. Entity extraction (async parallel chunks)
        3. Vector indexing (async Qdrant)
        4. CSV merging (async via thread pool)
        5. Entity deduplication (async)
        6. Normalization (async)
        7. S3 upload (async)

        Args:
            process_id: Pipeline run ID
            file_paths: List of paths to input files
            file_type: Type of files (pdf or xml)
            db_url: Database connection URL
            temp_dir: Temporary directory for processing
        """
        logger.info(f"Starting pipeline run {process_id} with {len(file_paths)} files")
        
        # Run entire pipeline in separate thread to prevent blocking API
        await asyncio.to_thread(
            self._run_pipeline_sync,
            process_id,
            file_paths,
            file_type,
            db_url,
            temp_dir
        )
    
    def _run_pipeline_sync(
        self,
        process_id: UUID,
        file_paths: list[str],
        file_type: str,
        db_url: str,
        temp_dir: str,
    ) -> None:
        """
        Synchronous wrapper that creates its own event loop for async operations.
        This runs in a separate thread via asyncio.to_thread().
        """
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(
                self._run_pipeline_async(process_id, file_paths, file_type, db_url, temp_dir)
            )
        finally:
            # Clean up pending tasks before closing
            try:
                # Cancel all remaining tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                
                # Wait for tasks to complete cancellation
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as e:
                logger.warning(f"Error during event loop cleanup: {e}")
            finally:
                # Close the loop
                loop.close()
    
    async def _run_pipeline_async(
        self,
        process_id: UUID,
        file_paths: list[str],
        file_type: str,
        db_url: str,
        temp_dir: str,
    ) -> None:
        """
        Internal async implementation of the pipeline execution.
        """
        # Import here to avoid circular dependencies
        from api.database import BackgroundSessionLocal
        from api.config import settings

        try:
            # Create async session for this task using background engine
            async with BackgroundSessionLocal() as db:
                # Update run to started
                try:
                    await self._update_run_status(
                        db, process_id, current_step="text_extraction", started_at=datetime.utcnow()
                    )
                    logger.info(f"Pipeline {process_id} marked as started")
                except Exception as e:
                    logger.error(f"Failed to mark pipeline {process_id} as started: {e}", exc_info=True)
                    raise

                # Get active prompt if exists
                try:
                    prompt_content = None
                    active_prompt = await PromptService.get_active_prompt(db)
                    if active_prompt:
                        prompt_content = active_prompt.prompt_content
                        logger.info(f"Using custom prompt version {active_prompt.version}")
                    else:
                        logger.info("No custom prompt found, will use default")
                except Exception as e:
                    logger.error(f"Failed to get active prompt for pipeline {process_id}: {e}", exc_info=True)
                    # Continue with default prompt
                    prompt_content = None

                # Create callbacks for status updates
                try:
                    status_callback = self._create_status_callback(db, process_id)
                    logger.debug(f"Created status callback for pipeline {process_id}")
                except Exception as e:
                    logger.error(f"Failed to create status callback for pipeline {process_id}: {e}", exc_info=True)
                    raise

                # Prepare output directory
                try:
                    output_dir = Path(temp_dir) / "results" / str(process_id)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created output directory: {output_dir}")
                except Exception as e:
                    logger.error(f"Failed to create output directory for pipeline {process_id}: {e}", exc_info=True)
                    raise

                # Copy files to expected directory structure
                try:
                    input_dir = Path(temp_dir) / "input"
                    input_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created input directory: {input_dir}")

                    for file_path in file_paths:
                        destination = input_dir / Path(file_path).name
                        shutil.copy(file_path, destination)
                        logger.debug(f"Copied {file_path} to {destination}")

                    logger.info(f"Copied {len(file_paths)} files to input directory")
                    
                    # Update total_documents count
                    await db.execute(
                        update(PipelineRun)
                        .where(PipelineRun.id == process_id)
                        .values(total_documents=len(file_paths))
                    )
                    await db.commit()
                    logger.info(f"Updated total_documents to {len(file_paths)}")
                except Exception as e:
                    logger.error(f"Failed to copy files for pipeline {process_id}: {e}", exc_info=True)
                    raise

                # Run the pipeline (from main.py)
                # Note: We'll need to modify main.py to accept these parameters
                await self._execute_pipeline(
                    db=db,
                    process_id=process_id,
                    input_dir=str(input_dir),
                    output_dir=str(output_dir),
                    file_type=file_type,
                    status_callback=status_callback,
                    custom_prompt=prompt_content,
                )

                # Upload results to S3
                try:
                    await self._update_run_status(
                        db, process_id, current_step="uploading_results"
                    )
                    logger.info(f"Starting S3 upload for pipeline {process_id}")

                    unique_entities_path = output_dir / "unique_entities.csv"
                    references_path = output_dir / "references.csv"

                    # Verify files exist before uploading
                    if not unique_entities_path.exists():
                        logger.error(f"Unique entities file not found: {unique_entities_path}")
                        raise Exception(f"Unique entities file not found: {unique_entities_path}")
                    if not references_path.exists():
                        logger.error(f"References file not found: {references_path}")
                        raise Exception(f"References file not found: {references_path}")

                    logger.debug(f"Unique entities file size: {unique_entities_path.stat().st_size} bytes")
                    logger.debug(f"References file size: {references_path.stat().st_size} bytes")

                    unique_s3_key, ref_s3_key = await self.s3_service.upload_pipeline_outputs(
                        str(process_id), str(unique_entities_path), str(references_path)
                    )

                    if not unique_s3_key or not ref_s3_key:
                        logger.error(f"Failed to upload outputs to S3 for pipeline {process_id}")
                        raise Exception("Failed to upload outputs to S3")

                    logger.info(f"Successfully uploaded outputs to S3 for pipeline {process_id}")

                    # Update run with S3 keys
                    await db.execute(
                        update(PipelineRun)
                        .where(PipelineRun.id == process_id)
                        .values(
                            unique_entities_s3_key=unique_s3_key,
                            references_s3_key=ref_s3_key,
                        )
                    )
                    await db.commit()
                    logger.info(f"Updated pipeline {process_id} with S3 keys")
                except Exception as e:
                    logger.error(f"Error during S3 upload for pipeline {process_id}: {e}", exc_info=True)
                    raise

                # Mark as completed
                try:
                    await self._update_run_status(
                        db,
                        process_id,
                        current_step="completed",
                        completed_at=datetime.utcnow(),
                    )
                    logger.info(f"Pipeline run {process_id} completed successfully")
                except Exception as e:
                    logger.error(f"Failed to mark pipeline {process_id} as completed: {e}", exc_info=True)
                    raise

        except Exception as e:
            logger.error(f"Pipeline run {process_id} failed: {e}", exc_info=True)
            try:
                # Import here since we're in background context
                from api.database import BackgroundSessionLocal
                
                async with BackgroundSessionLocal() as db:
                    await self._update_run_status(
                        db,
                        process_id,
                        current_step="failed",
                        error_message=str(e),
                        completed_at=datetime.utcnow(),
                    )
                    logger.info(f"Marked pipeline {process_id} as failed in database")
            except Exception as db_error:
                logger.error(f"Failed to mark pipeline {process_id} as failed in database: {db_error}", exc_info=True)

        finally:
            # Cleanup temporary files
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")

    async def _update_run_status(
        self,
        db: AsyncSession,
        process_id: UUID,
        current_step: Optional[str] = None,
        step_detail: Optional[str] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        **kwargs,
    ) -> None:
        """Update pipeline run status in database."""
        try:
            logger.debug(f"Updating pipeline run {process_id} status: step={current_step}, detail={step_detail}")

            update_values = {"updated_at": datetime.utcnow()}

            if current_step:
                update_values["current_step"] = current_step
            if step_detail:
                update_values["step_detail"] = step_detail
            if error_message:
                update_values["error_message"] = error_message
            if started_at:
                update_values["started_at"] = started_at
            if completed_at:
                update_values["completed_at"] = completed_at

            # Add any additional kwargs
            update_values.update(kwargs)

            await db.execute(
                update(PipelineRun).where(PipelineRun.id == process_id).values(**update_values)
            )
            await db.commit()
            logger.debug(f"Successfully updated pipeline run {process_id} status")
        except Exception as e:
            logger.error(f"Error updating pipeline run {process_id} status: {e}", exc_info=True)
            # Re-raise to allow caller to handle
            raise

    def _create_status_callback(self, db: AsyncSession, process_id: UUID) -> Callable:
        """
        Create a callback function for pipeline status updates.

        Returns:
            Async callback function that updates database
        """

        async def callback(
            step: str, message: str, details: Optional[dict] = None
        ) -> None:
            """Callback to update pipeline status."""
            logger.debug(f"Pipeline {process_id} status callback: {step} - {message}")
            try:
                # Add status update log
                try:
                    status_update = PipelineStatusUpdate(
                        run_id=process_id, step=step, message=message, details=details
                    )
                    db.add(status_update)
                    logger.debug(f"Added status update log for pipeline {process_id}")
                except Exception as e:
                    logger.error(f"Error adding status update log for pipeline {process_id}: {e}", exc_info=True)
                    # Continue even if logging fails

                # Update current step in run
                try:
                    await self._update_run_status(
                        db, process_id, current_step=step, step_detail=message
                    )
                    logger.info(f"Pipeline {process_id} - {step}: {message}")
                except Exception as e:
                    logger.error(f"Error updating run status for pipeline {process_id}: {e}", exc_info=True)
                    raise
                
                # Handle per-file progress updates from details
                if details and "filename" in details and "entities_count" in details:
                    try:
                        # Update processed_documents count
                        if "processed_documents" in details:
                            await db.execute(
                                update(PipelineRun)
                                .where(PipelineRun.id == process_id)
                                .values(processed_documents=details["processed_documents"])
                            )
                            await db.commit()
                        
                        # Update per-file entities_count and status
                        await db.execute(
                            update(InputFile)
                            .where(InputFile.run_id == process_id)
                            .where(InputFile.original_filename == details["filename"])
                            .values(
                                entities_count=details["entities_count"],
                                status=details.get("status", "completed")
                            )
                        )
                        await db.commit()
                        logger.debug(f"Updated file '{details['filename']}': entities={details['entities_count']}, status={details.get('status', 'completed')}")
                    except Exception as e:
                        logger.warning(f"Failed to update per-file progress: {e}")

            except Exception as e:
                logger.error(f"Failed to update pipeline status for {process_id}: {e}", exc_info=True)
                # Don't raise - allow pipeline to continue even if status update fails

        return callback

    async def _execute_pipeline(
        self,
        db: AsyncSession,
        process_id: UUID,
        input_dir: str,
        output_dir: str,
        file_type: str,
        status_callback: Callable,
        custom_prompt: Optional[str] = None,
    ) -> None:
        """
        Execute the main pipeline by calling process_document_directory() and
        copying the two final output files into the locations expected by the
        S3 upload step.

        Output mapping:
            unique_entities.csv  ←  results["unique_entities"]   (deduplicated entities)
            references.csv       ←  results["normalized_references"] (entity reference locations)

        Args:
            db: Database session
            process_id: Pipeline run ID
            input_dir: Directory containing input files
            output_dir: Directory for output files
            file_type: Type of input files (pdf / xml)
            status_callback: Async callback for status updates
            custom_prompt: Custom extraction prompt if provided
        """
        import pandas as pd
        from api.config import settings

        process_document_directory = _load_root_main().process_document_directory

        # ── run the real pipeline ─────────────────────────────────────
        results = await process_document_directory(
            input_dir=input_dir,
            output_dir=output_dir,
            file_type=file_type,
            extraction_provider="openai",
            extraction_model=settings.DEFAULT_EXTRACTION_MODEL,
            merging_provider="openai",
            merging_model=settings.DEFAULT_MERGING_MODEL,
            used_llamaparse=(file_type == "pdf"),
            enable_cost_tracking=settings.ENABLE_COST_TRACKING,
            use_iterative_dedup=settings.USE_ITERATIVE_DEDUP,
            iterative_dedup_max_rounds=settings.ITERATIVE_DEDUP_MAX_ROUNDS,
            status_callback=status_callback,
            custom_prompt=custom_prompt,
            process_id=str(process_id),
            max_concurrent_chunks=settings.MAX_CONCURRENT_CHUNKS
        )

        if not results:
            raise Exception("Pipeline returned no results – check logs for details")

        # ── locate the two deliverable files ──────────────────────────
        unique_entities_path = results.get("unique_entities")
        references_path = results.get("normalized_references")

        if not unique_entities_path or not os.path.exists(unique_entities_path):
            raise Exception(
                f"Unique entities file missing: {unique_entities_path}"
            )
        if not references_path or not os.path.exists(references_path):
            raise Exception(
                f"References file missing: {references_path}"
            )

        # ── copy to the canonical names the S3 upload step expects ────
        unique_entities_dest = Path(output_dir) / "unique_entities.csv"
        references_dest = Path(output_dir) / "references.csv"

        shutil.copy(unique_entities_path, unique_entities_dest)
        shutil.copy(references_path, references_dest)
        logger.info(f"Copied final outputs to {unique_entities_dest} and {references_dest}")

        # ── update entity counts into the pipeline_runs row ────────
        try:
            total_entities = 0
            unique_entities_count = 0

            merged_path = results.get("merged_results")
            if merged_path and os.path.exists(merged_path):
                total_entities = len(pd.read_csv(merged_path))
                logger.info(f"Read {total_entities} total entities from merged results")

            unique_entities_count = len(pd.read_csv(unique_entities_dest))
            logger.info(f"Read {unique_entities_count} unique entities from deduplicated results")

            total_documents = len(results.get("results_csv_files", []))
            # If no new docs were processed the list may be empty; fall back
            # to counting files in input_dir.
            if total_documents == 0:
                total_documents = len([
                    f for f in os.listdir(input_dir)
                    if f.lower().endswith(f".{file_type}")
                ])

            await db.execute(
                update(PipelineRun)
                .where(PipelineRun.id == process_id)
                .values(
                    total_documents=total_documents,
                    processed_documents=total_documents,
                    total_entities=total_entities,
                    unique_entities=unique_entities_count,
                )
            )
            await db.commit()
            logger.info(
                f"Pipeline {process_id}: total_docs={total_documents}, "
                f"total_entities={total_entities}, unique_entities={unique_entities_count}"
            )
        except Exception as e:
            # Counts are best-effort; don't kill the run over them
            logger.warning(f"Could not update entity counts for {process_id}: {e}")
