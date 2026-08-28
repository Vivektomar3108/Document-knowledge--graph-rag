"""
Pydantic schemas for pipeline-related endpoints.
"""

from pydantic import BaseModel, Field, UUID4
from typing import Optional, List
from datetime import datetime


class FileInfo(BaseModel):
    """Information about a single input file."""

    filename: str
    size_bytes: Optional[int] = None
    status: str
    entities_count: Optional[int] = None


class ProgressInfo(BaseModel):
    """Progress information for a pipeline run."""

    total_documents: int
    processed_documents: int
    total_entities: int
    unique_entities: Optional[int] = None


class TimingInfo(BaseModel):
    """Timing information for a pipeline run."""

    created_at: datetime
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PipelineStartResponse(BaseModel):
    """Response for POST /api/v1/pipeline/start"""

    process_id: UUID4
    current_step: str
    message: str
    created_at: datetime
    files: List[FileInfo]

    class Config:
        from_attributes = True


class PipelineStatusResponse(BaseModel):
    """Response for GET /api/v1/pipeline/{process_id}/status"""

    process_id: UUID4
    current_step: str
    step_detail: Optional[str] = None
    progress: ProgressInfo
    files: List[FileInfo]
    timing: TimingInfo
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class DownloadFileInfo(BaseModel):
    """Information about a downloadable file."""

    file_type: str
    description: str
    filename: str
    download_url: str
    expires_at: datetime


class PipelineFilesResponse(BaseModel):
    """Response for GET /api/v1/pipeline/{process_id}/files"""

    process_id: UUID4
    current_step: str
    completed_at: Optional[datetime] = None
    files: Optional[List[DownloadFileInfo]] = None
    summary: Optional[dict] = None
    error: Optional[str] = None
    message: Optional[str] = None

    class Config:
        from_attributes = True


class PipelineRunSummary(BaseModel):
    """Summary information for a pipeline run."""

    process_id: UUID4
    current_step: str
    file_type: str
    total_files: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    total_entities: int
    unique_entities: Optional[int] = None


class PaginationInfo(BaseModel):
    """Pagination metadata."""

    page: int
    per_page: int
    total_items: int
    total_pages: int


class PipelineRunListResponse(BaseModel):
    """Response for GET /api/v1/pipeline/runs"""

    runs: List[PipelineRunSummary]
    pagination: PaginationInfo

    class Config:
        from_attributes = True
