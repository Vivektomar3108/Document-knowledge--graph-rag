"""
Pipeline management endpoints.
"""

import os
import math
from pathlib import Path
from typing import List
from uuid import UUID
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    BackgroundTasks,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from api.database import get_db
from api.dependencies import verify_api_key
from api.config import settings
from api.models.pipeline import PipelineRun, InputFile
from api.services.s3_service import S3Service
from api.services.pipeline_runner import PipelineRunner
from api.services.prompt_service import PromptService
from api.schemas.pipeline import (
    PipelineStartResponse,
    PipelineStatusResponse,
    PipelineFilesResponse,
    PipelineRunListResponse,
    FileInfo,
    ProgressInfo,
    TimingInfo,
    DownloadFileInfo,
    PipelineRunSummary,
    PaginationInfo,
)
from logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])

# Initialize services
s3_service = S3Service()
pipeline_runner = PipelineRunner(s3_service)


@router.post("/start", response_model=PipelineStartResponse, status_code=status.HTTP_201_CREATED)
async def start_pipeline(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Start a new pipeline run with multiple file uploads.

    All files must be the same type (either all PDF or all XML).

    Args:
        files: List of uploaded files (PDF or XML)

    Returns:
        Process ID and initial status
    """
    logger.info(f"Received pipeline start request with {len(files)} files")

    try:
        # Validation: Check if files are provided
        if not files:
            logger.warning("Pipeline start rejected: No files provided")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No files provided. Please upload at least one file.",
            )

        # Validation: Check max files limit
        if len(files) > settings.MAX_FILES_PER_REQUEST:
            logger.warning(f"Pipeline start rejected: Too many files ({len(files)} > {settings.MAX_FILES_PER_REQUEST})")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Too many files. Maximum {settings.MAX_FILES_PER_REQUEST} files allowed per request.",
            )

        # Validation: Check file types and ensure all are same type
        file_extensions = set()
        for file in files:
            ext = Path(file.filename).suffix.lower()
            if ext not in settings.ALLOWED_FILE_EXTENSIONS:
                logger.warning(f"Pipeline start rejected: Invalid file type {ext} for file {file.filename}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid file type: {file.filename}. Only PDF and XML files are allowed.",
                )
            file_extensions.add(ext)

        # Check for mixed file types
        if len(file_extensions) > 1:
            logger.warning(f"Pipeline start rejected: Mixed file types {file_extensions}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mixed file types detected. All files must be the same type (either all PDF or all XML).",
            )

        # Determine file type
        file_type = "pdf" if ".pdf" in file_extensions else "xml"
        logger.info(f"Validated file type: {file_type}")

        # Get active prompt
        try:
            active_prompt = await PromptService.get_active_prompt(db)
            prompt_version_id = active_prompt.id if active_prompt else None
            if active_prompt:
                logger.info(f"Using active prompt version {active_prompt.version}")
            else:
                logger.info("No active prompt found, will use default")
        except Exception as e:
            logger.error(f"Failed to get active prompt: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve prompt configuration. Please try again.",
            )

        # Create pipeline run record
        try:
            run = PipelineRun(
                file_type=file_type,
                total_files=len(files),
                current_step="pending",
                extraction_model=settings.DEFAULT_EXTRACTION_MODEL,
                merging_model=settings.DEFAULT_MERGING_MODEL,
                prompt_version_id=prompt_version_id,
            )

            db.add(run)
            await db.flush()  # Get the ID without committing
            process_id = run.id
            logger.info(f"Created pipeline run record with ID: {process_id}")
        except Exception as e:
            logger.error(f"Failed to create pipeline run record: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create pipeline run. Please try again.",
            )

        # Create temp directory for this run
        try:
            temp_dir = Path(settings.TEMP_UPLOAD_DIR) / str(process_id)
            temp_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created temporary directory: {temp_dir}")
        except Exception as e:
            logger.error(f"Failed to create temporary directory: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create temporary storage. Please try again.",
            )

        # Save uploaded files and create InputFile records
        file_paths = []
        input_file_records = []

        for file in files:
            try:
                # Check file size
                file.file.seek(0, 2)  # Seek to end
                file_size = file.file.tell()
                file.file.seek(0)  # Reset to beginning

                if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
                    logger.warning(f"File {file.filename} exceeds size limit: {file_size} bytes")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File {file.filename} exceeds maximum size of {settings.MAX_FILE_SIZE_MB}MB.",
                    )

                # Save file to temp directory
                file_path = temp_dir / file.filename
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)

                logger.info(f"Saved file {file.filename} ({file_size} bytes) to {file_path}")
                file_paths.append(str(file_path))

                # Create InputFile record
                input_file = InputFile(
                    run_id=process_id,
                    original_filename=file.filename,
                    file_size_bytes=file_size,
                    status="pending",
                )
                db.add(input_file)
                input_file_records.append(
                    FileInfo(
                        filename=file.filename, size_bytes=file_size, status="pending"
                    )
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to save file {file.filename}: {e}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to save file {file.filename}. Please try again.",
                )

        # Commit all database changes
        try:
            await db.commit()
            await db.refresh(run)
            logger.info(f"Committed database records for pipeline run {process_id}")
        except Exception as e:
            logger.error(f"Failed to commit database changes: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save pipeline configuration. Please try again.",
            )

        # Start pipeline in background
        try:
            background_tasks.add_task(
                pipeline_runner.run_pipeline,
                process_id=process_id,
                file_paths=file_paths,
                file_type=file_type,
                db_url=settings.DATABASE_URL,
                temp_dir=str(temp_dir),
            )
            logger.info(f"Scheduled background task for pipeline run {process_id}")
        except Exception as e:
            logger.error(f"Failed to schedule background task: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start pipeline. Please try again.",
            )

        logger.info(
            f"Successfully started pipeline run {process_id} with {len(files)} {file_type} files"
        )

        return PipelineStartResponse(
            process_id=process_id,
            current_step=run.current_step,
            message=f"Pipeline started successfully. Processing {len(files)} files.",
            created_at=run.created_at,
            files=input_file_records,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in start_pipeline: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )


@router.get("/{process_id}/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    process_id: UUID,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Get the current status of a pipeline run.

    Args:
        process_id: Pipeline run process ID

    Returns:
        Current status with step visibility and progress
    """
    logger.info(f"Retrieving status for pipeline run {process_id}")

    try:
        # Get pipeline run
        try:
            result = await db.execute(select(PipelineRun).where(PipelineRun.id == process_id))
            run = result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Database error retrieving pipeline run {process_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve pipeline status. Please try again.",
            )

        if not run:
            logger.warning(f"Pipeline run {process_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pipeline run {process_id} not found",
            )

        logger.info(f"Pipeline run {process_id} found with status: {run.current_step}")

        # Get input files
        try:
            files_result = await db.execute(
                select(InputFile).where(InputFile.run_id == process_id)
            )
            input_files = files_result.scalars().all()
            logger.info(f"Retrieved {len(input_files)} input files for pipeline run {process_id}")
        except Exception as e:
            logger.error(f"Database error retrieving input files for {process_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve input files information. Please try again.",
            )

        # Build response
        try:
            files_info = [
                FileInfo(
                    filename=f.original_filename,
                    size_bytes=f.file_size_bytes,
                    status=f.status,
                    entities_count=f.entities_count,
                )
                for f in input_files
            ]

            progress = ProgressInfo(
                total_documents=run.total_documents,
                processed_documents=run.processed_documents,
                total_entities=run.total_entities,
                unique_entities=run.unique_entities,
            )

            timing = TimingInfo(
                created_at=run.created_at,
                started_at=run.started_at,
                updated_at=run.updated_at,
                completed_at=run.completed_at,
            )

            logger.info(f"Successfully built status response for pipeline run {process_id}")

            return PipelineStatusResponse(
                process_id=process_id,
                current_step=run.current_step,
                step_detail=run.step_detail,
                progress=progress,
                files=files_info,
                timing=timing,
                error_message=run.error_message,
            )
        except Exception as e:
            logger.error(f"Error building status response for {process_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to build status response. Please try again.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_pipeline_status for {process_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )


@router.get("/{process_id}/files", response_model=PipelineFilesResponse)
async def get_pipeline_files(
    process_id: UUID,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Get download URLs for generated files.

    Only available after pipeline completion.

    Args:
        process_id: Pipeline run process ID

    Returns:
        Download URLs for final output files
    """
    logger.info(f"Retrieving download URLs for pipeline run {process_id}")

    try:
        # Get pipeline run
        try:
            result = await db.execute(select(PipelineRun).where(PipelineRun.id == process_id))
            run = result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Database error retrieving pipeline run {process_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve pipeline information. Please try again.",
            )

        if not run:
            logger.warning(f"Pipeline run {process_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pipeline run {process_id} not found",
            )

        logger.info(f"Pipeline run {process_id} found with status: {run.current_step}")

        # Check if pipeline failed
        if run.current_step == "failed":
            logger.warning(f"Pipeline run {process_id} has failed status")
            return PipelineFilesResponse(
                process_id=process_id,
                current_step=run.current_step,
                error="pipeline_failed",
                message=f"Pipeline failed during {run.current_step} step.",
            )

        # Check if pipeline completed
        if run.current_step != "completed":
            logger.info(f"Pipeline run {process_id} is still running (status: {run.current_step})")
            return PipelineFilesResponse(
                process_id=process_id,
                current_step=run.current_step,
                error="files_not_ready",
                message="Pipeline is still running. Files will be available after completion.",
            )

        # Generate presigned URLs
        try:
            expiry_time = s3_service.get_expiry_time()
            logger.info(f"Generating presigned URLs for pipeline run {process_id}")

            unique_entities_url = await s3_service.generate_presigned_url(
                run.unique_entities_s3_key
            )
            references_url = await s3_service.generate_presigned_url(run.references_s3_key)

            if not unique_entities_url or not references_url:
                logger.error(f"Failed to generate presigned URLs for pipeline run {process_id}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to generate download URLs. Please try again later.",
                )

            logger.info(f"Successfully generated presigned URLs for pipeline run {process_id}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error generating presigned URLs for {process_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate download URLs. Please try again.",
            )

        # Build response
        try:
            files = [
                DownloadFileInfo(
                    file_type="unique_entities_csv",
                    description="Deduplicated unique entities",
                    filename="unique_entities.csv",
                    download_url=unique_entities_url,
                    expires_at=expiry_time,
                ),
                DownloadFileInfo(
                    file_type="references_csv",
                    description="Entity reference locations",
                    filename="references.csv",
                    download_url=references_url,
                    expires_at=expiry_time,
                ),
            ]

            summary = {
                "total_documents": run.total_documents,
                "total_entities": run.total_entities,
                "unique_entities": run.unique_entities,
            }

            logger.info(f"Successfully built files response for pipeline run {process_id}")

            return PipelineFilesResponse(
                process_id=process_id,
                current_step=run.current_step,
                completed_at=run.completed_at,
                files=files,
                summary=summary,
            )
        except Exception as e:
            logger.error(f"Error building files response for {process_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to build response. Please try again.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_pipeline_files for {process_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )


@router.get("/runs", response_model=PipelineRunListResponse)
async def list_pipeline_runs(
    page: int = 1,
    per_page: int = 20,
    current_step: str = None,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    List all pipeline runs with pagination.

    Args:
        page: Page number (1-indexed)
        per_page: Items per page (max 100)
        current_step: Optional filter by current step

    Returns:
        List of pipeline runs with pagination info
    """
    filter_msg = f" with filter current_step={current_step}" if current_step else ""
    logger.info(f"Listing pipeline runs (page={page}, per_page={per_page}{filter_msg})")

    try:
        # Validate pagination
        if page < 1:
            page = 1
        if per_page > 100:
            per_page = 100

        # Build query
        try:
            query = select(PipelineRun).order_by(desc(PipelineRun.created_at))

            if current_step:
                query = query.where(PipelineRun.current_step == current_step)

            # Get total count
            count_query = select(func.count(PipelineRun.id))
            if current_step:
                count_query = count_query.where(PipelineRun.current_step == current_step)

            count_result = await db.execute(count_query)
            total_count = count_result.scalar()
            logger.info(f"Found {total_count} total pipeline runs{filter_msg}")

            # Get paginated results
            offset = (page - 1) * per_page
            query = query.limit(per_page).offset(offset)

            result = await db.execute(query)
            runs = result.scalars().all()
            logger.info(f"Retrieved {len(runs)} pipeline runs for page {page}")
        except Exception as e:
            logger.error(f"Database error listing pipeline runs: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve pipeline runs. Please try again.",
            )

        # Build response
        try:
            run_summaries = [
                PipelineRunSummary(
                    process_id=run.id,
                    current_step=run.current_step,
                    file_type=run.file_type,
                    total_files=run.total_files,
                    created_at=run.created_at,
                    completed_at=run.completed_at,
                    total_entities=run.total_entities,
                    unique_entities=run.unique_entities,
                )
                for run in runs
            ]

            total_pages = math.ceil(total_count / per_page) if total_count > 0 else 1

            logger.info(f"Successfully built list response with {len(run_summaries)} runs")

            return PipelineRunListResponse(
                runs=run_summaries,
                pagination=PaginationInfo(
                    page=page,
                    per_page=per_page,
                    total_items=total_count,
                    total_pages=total_pages,
                ),
            )
        except Exception as e:
            logger.error(f"Error building list response: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to build response. Please try again.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in list_pipeline_runs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please contact support.",
        )
