"""
SQLAlchemy model for extraction prompts.
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    Boolean,
    DateTime,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from api.database import Base


class ExtractionPrompt(Base):
    """Store custom extraction prompts with version tracking."""

    __tablename__ = "extraction_prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Version tracking
    version = Column(Integer, nullable=False, unique=True)
    is_active = Column(Boolean, default=False)

    # Prompt content
    prompt_name = Column(String(200), nullable=False)
    prompt_content = Column(Text, nullable=False)

    # Audit
    created_by = Column(String(200), nullable=True)
    change_notes = Column(Text, nullable=True)

    # Hash for quick comparison
    content_hash = Column(String(64), nullable=False)  # SHA256

    # Indexes and constraints
    __table_args__ = (
        Index("idx_extraction_prompts_version", "version"),
        Index(
            "idx_extraction_prompts_is_active",
            "is_active",
            postgresql_where=text("is_active = true"),
        ),
        # Ensure only one active prompt (partial unique index)
        Index(
            "idx_single_active_prompt",
            "is_active",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )
