"""Knowledge-graph vocabulary and the strict schemas used to validate extracted facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class NodeType(str, Enum):
    STUDENT = "Student"
    COURSE = "Course"
    MODULE = "Module"
    LECTURE = "Lecture"
    RESOURCE = "Resource"
    CONCEPT = "Concept"
    TOPIC = "Topic"
    METHOD = "Method"
    ALGORITHM = "Algorithm"
    FORMULA = "Formula"
    EXAMPLE = "Example"
    ASSIGNMENT = "Assignment"
    QUIZ = "Quiz"


# Concept-like node types: all participate in semantic relations and entity resolution.
CONCEPT_TYPES = {
    NodeType.CONCEPT, NodeType.TOPIC, NodeType.METHOD, NodeType.ALGORITHM, NodeType.FORMULA,
    NodeType.EXAMPLE,
}


class Relation(str, Enum):
    # structural
    ENROLLED_IN = "ENROLLED_IN"
    HAS_MODULE = "HAS_MODULE"
    HAS_LECTURE = "HAS_LECTURE"
    HAS_RESOURCE = "HAS_RESOURCE"
    HAS_ASSIGNMENT = "HAS_ASSIGNMENT"
    INTRODUCED_IN = "INTRODUCED_IN"
    EXPLAINED_IN = "EXPLAINED_IN"
    ASSESSED_IN = "ASSESSED_IN"
    REVISITED_IN = "REVISITED_IN"
    ASSESSES = "ASSESSES"
    # semantic (concept -> concept, or lecture -> lecture for BUILDS_ON)
    REQUIRES = "REQUIRES"
    BUILDS_ON = "BUILDS_ON"
    USES = "USES"
    EXTENDS = "EXTENDS"
    CONTRASTS_WITH = "CONTRASTS_WITH"
    TYPE_OF = "TYPE_OF"
    PART_OF = "PART_OF"
    DERIVED_FROM = "DERIVED_FROM"
    EXAMPLE_OF = "EXAMPLE_OF"
    RELATED_TO = "RELATED_TO"
    APPLIED_IN = "APPLIED_IN"


SEMANTIC_RELATIONS = {
    Relation.REQUIRES, Relation.BUILDS_ON, Relation.USES, Relation.EXTENDS,
    Relation.CONTRASTS_WITH, Relation.TYPE_OF, Relation.PART_OF, Relation.DERIVED_FROM,
    Relation.EXAMPLE_OF, Relation.RELATED_TO, Relation.APPLIED_IN,
}

# Edges followed when answering "what do I need before X?" (X -> prerequisite direction).
PREREQUISITE_RELATIONS = {
    Relation.REQUIRES, Relation.BUILDS_ON, Relation.USES, Relation.EXTENDS, Relation.TYPE_OF,
    Relation.DERIVED_FROM,
}

LECTURE_RELATIONS = {Relation.INTRODUCED_IN, Relation.EXPLAINED_IN, Relation.REVISITED_IN, Relation.APPLIED_IN}


class ExtractionMethod(str, Enum):
    STRUCTURAL = "structural"  # derived from course structure (week, file, heading)
    HEADING = "slide_heading"
    PATTERN = "lexical_pattern"  # explicit textual cue ("X is a type of Y")
    SLIDE_FIELD = "slide_field"  # labelled slide field ("Optimization: Gradient descent")
    RECAP = "recap_slide"  # "Revision:/Recap:" slide in a later lecture
    LLM = "llm_structured"
    MENTION = "explicit_mention"
    SEMANTIC = "semantic_similarity"


# ----------------------------------------------------------------------- LLM extraction schema

ALLOWED_LLM_CONCEPT_TYPES = ["Concept", "Method", "Algorithm", "Formula", "Topic", "Example"]
ALLOWED_LLM_RELATIONS = sorted(r.value for r in SEMANTIC_RELATIONS)


class ExtractedConcept(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    type: str = "Concept"
    aliases: list[str] = Field(default_factory=list, max_length=6)
    description: Optional[str] = Field(default=None, max_length=300)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        return v if v in ALLOWED_LLM_CONCEPT_TYPES else "Concept"


class ExtractedRelation(BaseModel):
    source: str = Field(min_length=2, max_length=80)
    relation: str
    target: str = Field(min_length=2, max_length=80)
    evidence_quote: str = Field(min_length=8, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("relation")
    @classmethod
    def _rel(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if v not in ALLOWED_LLM_RELATIONS:
            raise ValueError(f"unsupported relation {v}")
        return v


class ChunkExtraction(BaseModel):
    concepts: list[ExtractedConcept] = Field(default_factory=list, max_length=25)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=25)


def llm_json_schema() -> dict:
    """JSON schema passed to the LLM's structured-output mode."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["concepts", "relations"],
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "type", "aliases", "description"],
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": ALLOWED_LLM_CONCEPT_TYPES},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"},
                    },
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source", "relation", "target", "evidence_quote", "confidence"],
                    "properties": {
                        "source": {"type": "string"},
                        "relation": {"type": "string", "enum": ALLOWED_LLM_RELATIONS},
                        "target": {"type": "string"},
                        "evidence_quote": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                },
            },
        },
    }


# ----------------------------------------------------------------------- runtime graph objects


@dataclass
class GraphNode:
    node_id: str
    node_type: str
    node_key: str
    label: str
    course_id: str
    description: Optional[str] = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeEvidence:
    chunk_id: Optional[str]
    resource_id: Optional[str]
    page_number: Optional[int] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    quote: Optional[str] = None
    extraction_method: str = ExtractionMethod.PATTERN.value


@dataclass
class GraphEdge:
    edge_id: str
    source_node_id: str
    relation: str
    target_node_id: str
    confidence: float
    extraction_method: str
    course_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    evidence: list[EdgeEvidence] = field(default_factory=list)
