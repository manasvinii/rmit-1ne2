"""Normalized lecture-resource, segment and chunk models shared by every ingestion path."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResourceType(str, Enum):
    PDF = "pdf"
    SLIDES = "slides"
    VIDEO = "video"
    PAGE = "page"  # Canvas wiki page
    EXTERNAL_URL = "external_url"
    EXTERNAL_TOOL = "external_tool"  # LTI (e.g. lecture-capture); metadata only
    FILE = "file"  # Canvas file of unsupported/unknown type
    TRANSCRIPT = "transcript"


class SourceProvider(str, Enum):
    LOCAL = "local"
    CANVAS = "canvas"
    LTI = "lti"


class IngestionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # e.g. external LTI resource with no approved integration


class ContentType(str, Enum):
    PDF_PAGE = "pdf_page"
    SLIDE = "slide"
    TRANSCRIPT = "transcript"
    CANVAS_PAGE = "canvas_page"
    NOTEBOOK = "notebook"  # lab notebook section; page_number is the starting cell


class LectureResource(BaseModel):
    resource_id: str
    canvas_course_id: str
    user_id: str
    module_id: Optional[str] = None
    module_name: Optional[str] = None
    title: str
    resource_type: ResourceType
    mime_type: Optional[str] = None
    canvas_url: Optional[str] = None
    download_url: Optional[str] = None  # never returned to the frontend
    local_path: Optional[str] = None  # never returned to the frontend
    source_provider: SourceProvider
    week: Optional[int] = None
    lecture_number: Optional[int] = None
    is_external: bool = False
    content_hash: Optional[str] = None
    source_updated_at: Optional[str] = None
    size_bytes: Optional[int] = None
    status: IngestionStatus = IngestionStatus.PENDING
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def lecture_label(self) -> str:
        if self.week is not None:
            return f"Week {self.week}"
        return self.module_name or self.title


class TranscriptSegment(BaseModel):
    start_time: float
    end_time: float
    text: str


class ContentChunk(BaseModel):
    """A retrievable unit of evidence. Provenance fields are mandatory by construction."""

    chunk_id: str
    user_id: str
    course_id: str
    resource_id: str
    lecture_id: str  # lecture node key, e.g. "<course>:week:3"
    content_type: ContentType
    text: str
    heading: Optional[str] = None
    module: Optional[str] = None
    week: Optional[int] = None
    resource_title: str
    page_number: Optional[int] = None
    page_end: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    source_url: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = None

    def provenance(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "lecture_id": self.lecture_id,
            "module": self.module,
            "week": self.week,
            "resource_id": self.resource_id,
            "resource_title": self.resource_title,
            "page": self.page_number,
            "page_end": self.page_end,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "source_url": self.source_url,
            "chunk_id": self.chunk_id,
        }


def lecture_key(course_id: str, week: Optional[int], fallback: str) -> str:
    return f"{course_id}:week:{week}" if week is not None else f"{course_id}:lecture:{fallback}"
