"""Evaluation dataset format (one JSON object per line).

{
  "id": "relu-fact",
  "question": "What is ReLU?",
  "course_id": "COSC2673",
  "category": "fact | locate | prerequisite | timeline | connection | relation | assignment | structured",
  "expected_route": "VECTOR_RAG",                       # optional
  "expected_evidence": [                                 # gold evidence locations (any order)
    {"type": "slides", "week": 8, "pages": [42, 42]},    # inclusive slide/page range
    {"type": "video", "week": 7, "time": [560, 700]}     # seconds; matched by overlap
  ],
  "expected_concepts": ["ReLU"],                         # should be named in the answer
  "label_status": "draft | reviewed",                    # only 'reviewed' items belong in reported numbers
  "notes": "where the label came from"
}
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["fact", "locate", "prerequisite", "timeline", "connection", "relation", "assignment", "structured"]


class GoldEvidence(BaseModel):
    type: Literal["slides", "pdf", "video", "canvas"]
    week: Optional[int] = None
    pages: Optional[tuple[int, int]] = None
    time: Optional[tuple[float, float]] = None

    def matches(self, source: dict) -> bool:
        stype = source.get("type")
        if self.type in ("slides", "pdf") and stype not in ("slides", "pdf"):
            return False
        if self.type in ("video", "canvas") and stype != self.type:
            return False
        if self.week is not None and source.get("week") != self.week:
            return False
        if self.pages:
            lo, hi = self.pages
            p0 = source.get("page")
            p1 = source.get("page_end") or p0
            return p0 is not None and p0 <= hi and p1 >= lo
        if self.time:
            lo, hi = self.time
            s0, s1 = source.get("start_time"), source.get("end_time")
            return s0 is not None and s1 is not None and s0 <= hi and s1 >= lo
        return True


class EvalItem(BaseModel):
    id: str
    question: str
    course_id: Optional[str] = None
    category: Category
    expected_route: Optional[str] = None
    expected_evidence: list[GoldEvidence] = Field(default_factory=list)
    expected_concepts: list[str] = Field(default_factory=list)
    label_status: Literal["draft", "reviewed"] = "draft"
    notes: Optional[str] = None
