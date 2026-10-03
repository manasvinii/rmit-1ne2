"""Public API request/response contracts."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    api_token: Optional[str] = Field(default=None, max_length=512, description="Canvas access token")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user_id: str
    name: Optional[str] = None
    expires_in: int


class CanvasTokenUpdate(BaseModel):
    api_token: str = Field(min_length=10, max_length=512)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1, max_length=2000)
    course_id: Optional[Union[str, int]] = None
    fast: bool = False  # skip the LLM and compose the answer directly from the evidence
    # Accepted for backwards compatibility but never trusted: identity comes from the session.
    user_id: Optional[Union[str, int]] = None

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        return v


SourceType = Literal["pdf", "slides", "video", "canvas", "graph"]


class Source(BaseModel):
    id: str  # citation marker used in the reply, e.g. "S1"
    type: SourceType
    title: str
    course_id: Optional[str] = None
    week: Optional[int] = None
    module: Optional[str] = None
    page: Optional[int] = None
    page_end: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    timestamp: Optional[str] = None  # "18:03–22:40"
    url: Optional[str] = None  # authorised link (signed, short-lived) or Canvas URL
    snippet: Optional[str] = None
    support: Literal["direct", "inferred"] = "direct"
    relation: Optional[str] = None  # human-readable graph relationship this source supports
    aligned_slide: Optional[str] = None  # "Week 7 slides p.14" for transcript chunks


class QueryResponse(BaseModel):
    reply: str
    sources: list[Source] = Field(default_factory=list)
    route: str
    confidence: float = Field(ge=0.0, le=1.0)
    intent: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class TeachStartRequest(BaseModel):
    subject_id: Union[str, int] = Field(alias="subjectId")
    week: Optional[int] = Field(default=None, ge=1, le=20)
    mode: Literal["single", "range"] = "single"
    weeks: Optional[list[int]] = Field(default=None, max_length=20)  # any combination; wins over week/mode
    persona: Literal["pip", "sage", "milo"] = "pip"
    input: Literal["voice", "text"] = "voice"
    length: int = Field(default=15, ge=5, le=60)
    exclude: list[str] = Field(default_factory=list, max_length=200)
    include: list[str] = Field(default_factory=list, max_length=200)
    fast: bool = False  # skip the LLM: deterministic persona (instant replies)

    model_config = ConfigDict(populate_by_name=True)


class TeachTurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    via: Literal["voice", "text"] = "text"


class TeachReteachRequest(BaseModel):
    persona: Optional[Literal["pip", "sage", "milo"]] = None  # another student: all ideas, not just weak spots
    fast: bool = False


class QuizRequest(BaseModel):
    course_id: Optional[Union[str, int]] = None
    assignment_id: Optional[Union[str, int]] = None
    week: Optional[int] = Field(default=None, ge=1, le=20)
    num_questions: int = Field(default=5, ge=1, le=10)
    fast: bool = False


class IngestLocalRequest(BaseModel):
    course_id: str = Field(min_length=1, max_length=64)
    subdirectory: Optional[str] = Field(default=None, max_length=200)
    force: bool = False
    build_graph: bool = True
    use_llm: bool = True
