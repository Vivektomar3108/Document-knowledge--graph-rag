"""
SQLAlchemy models for pipeline-related tables.
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from api.database import Base


class PipelineRun(Base):
    """
    Track each pipeline execution.
    The 'id' field is the process_id used for tracking.
    """

    __tablename__ = "pipeline_runs"

    # Primary identifier (this is the process_id)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Run Configuration
    file_type = Column(
        String(10), nullable=False, comment="pdf or xml"
    )  # CheckConstraint in DB
    total_files = Column(Integer, nullable=False, default=0)

    # Model Configuration (fixed defaults)
    extraction_model = Column(String(100), nullable=False, default="gpt-4.1")
    merging_model = Column(String(100), nullable=False, default="gpt-4.1-mini")

    # Current Pipeline Step
    current_step = Column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending, text_extraction, entity_extraction, vector_indexing, csv_merging, entity_deduplication, normalization, uploading_results, completed, failed",
    )

    # Step-specific progress detail
    step_detail = Column(String(500), nullable=True)

    # Overall Progress
    total_documents = Column(Integer, default=0)
    processed_documents = Column(Integer, default=0)
    total_entities = Column(Integer, default=0)
    unique_entities = Column(Integer, nullable=True)  # Only after deduplication

    # Prompt Configuration
    prompt_version_id = Column(
        UUID(as_uuid=True), ForeignKey("extraction_prompts.id"), nullable=True
    )

    # Error Handling
    error_message = Column(Text, nullable=True)

    # S3 Output Keys
    unique_entities_s3_key = Column(String(1000), nullable=True)
    references_s3_key = Column(String(1000), nullable=True)

    # Relationships
    input_files = relationship(
        "InputFile", back_populates="run", cascade="all, delete-orphan"
    )
    status_updates = relationship(
        "PipelineStatusUpdate", back_populates="run", cascade="all, delete-orphan"
    )
    prompt = relationship("ExtractionPrompt", foreign_keys=[prompt_version_id])

    # Indexes
    __table_args__ = (
        Index("idx_pipeline_runs_current_step", "current_step"),
        Index("idx_pipeline_runs_created_at", "created_at"),
        CheckConstraint(
            "file_type IN ('pdf', 'xml')", name="check_file_type"
        ),
        CheckConstraint(
            "current_step IN ('pending', 'text_extraction', 'entity_extraction', 'vector_indexing', 'csv_merging', 'entity_deduplication', 'normalization', 'uploading_results', 'completed', 'failed')",
            name="check_current_step",
        ),
    )


class InputFile(Base):
    """Track input files per pipeline run."""

    __tablename__ = "input_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    # File Information
    original_filename = Column(String(500), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)

    # Processing Status
    status = Column(
        String(30),
        nullable=False,
        default="pending",
        comment="pending, processing, completed, failed",
    )

    # Per-file metrics
    entities_count = Column(Integer, default=0)

    # Relationships
    run = relationship("PipelineRun", back_populates="input_files")

    # Indexes
    __table_args__ = (
        Index("idx_input_files_run_id", "run_id"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="check_status",
        ),
    )


class PipelineStatusUpdate(Base):
    """Detailed status log for pipeline runs."""

    __tablename__ = "pipeline_status_updates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    step = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(JSONB, nullable=True)  # Additional context

    # Relationships
    run = relationship("PipelineRun", back_populates="status_updates")

    # Indexes
    __table_args__ = (
        Index("idx_status_updates_run_id", "run_id"),
        Index("idx_status_updates_created_at", "created_at"),
    )
