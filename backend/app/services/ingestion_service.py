"""Incremental ingestion orchestrator.

  discover resource -> compare content hash with stored version
     unchanged  -> skip
     new/changed -> extract (PDF pages | video transcript) -> chunk -> embed -> store chunks
                 -> align transcript chunks to slides -> rebuild course knowledge graph
Status per resource: pending -> processing -> completed | failed | skipped
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from app.database.graph_repository import GraphRepository
from app.database.resource_repository import ResourceRepository
from app.database.vector_repository import ChunkFilter, VectorRepository
from app.models.resource_models import (
    ContentChunk,
    ContentType,
    IngestionStatus,
    LectureResource,
    ResourceType,
    lecture_key,
)
from app.services import document_service, video_service
from app.services.embedding_service import Embedder, get_embedder
from app.services.graph_extraction_service import build_course_graph
from app.services.resource_ids import file_sha256, make_chunk_id

log = logging.getLogger(__name__)

ALIGN_MIN_SIMILARITY = 0.55


@dataclass
class IngestionReport:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    external: list[str] = field(default_factory=list)
    graph: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "processed": self.processed,
            "skipped_unchanged": self.skipped,
            "failed": self.failed,
            "external_not_ingested": self.external,
            "graph": self.graph,
        }


class IngestionService:
    def __init__(
        self,
        resources: Optional[ResourceRepository] = None,
        vectors: Optional[VectorRepository] = None,
        graph: Optional[GraphRepository] = None,
        embedder: Optional[Embedder] = None,
        transcriber: Optional[video_service.Transcriber] = None,
        progress: Optional[Callable[[str], None]] = None,
    ):
        self.resources = resources or ResourceRepository()
        self.vectors = vectors or VectorRepository()
        self.graph = graph or GraphRepository()
        self.embedder = embedder or get_embedder()
        self.transcriber = transcriber
        self.progress = progress or (lambda msg: log.info(msg))

    # ------------------------------------------------------------------ entry points
    def ingest(self, discovered: list[LectureResource], force: bool = False, build_graph: bool = True,
               use_llm: bool = True) -> IngestionReport:
        report = IngestionReport()
        courses: set[tuple[str, str]] = set()
        # documents first so videos can be aligned against slides
        order = sorted(discovered, key=lambda r: (r.resource_type == ResourceType.VIDEO, r.week or 99, r.title))
        for res in order:
            courses.add((res.user_id, res.canvas_course_id))
            try:
                outcome = self.ingest_resource(res, force=force)
            except Exception as e:  # one bad file must not stop the batch
                log.exception("Ingestion failed for %s", res.title)
                self.resources.set_status(res.user_id, res.resource_id, IngestionStatus.FAILED, error=str(e)[:500])
                report.failed[res.title] = str(e)[:200]
                continue
            {"processed": report.processed, "skipped": report.skipped, "external": report.external}[outcome].append(res.title)
        if build_graph and (report.processed or force):
            for user_id, course_id in courses:
                self.progress(f"Building knowledge graph for course {course_id}")
                report.graph = build_course_graph(
                    user_id, course_id, graph_repo=self.graph, vector_repo=self.vectors,
                    resource_repo=self.resources, use_llm=use_llm, embed=self.embedder.embed,
                )
        return report

    def ingest_resource(self, res: LectureResource, force: bool = False) -> str:
        existing = self.resources.get(res.user_id, res.resource_id)
        if existing is not None:
            # keep facts learned during previous ingestion (deck title, inferred week of a recording)
            res.metadata = {**{k: v for k, v in existing.metadata.items() if k != "error"}, **res.metadata}
            if res.week is None and existing.week is not None:
                res.week, res.module_name = existing.week, res.module_name or existing.module_name
        self.resources.upsert(res)

        if res.is_external or res.resource_type in (ResourceType.EXTERNAL_TOOL, ResourceType.EXTERNAL_URL):
            self.resources.set_status(
                res.user_id, res.resource_id, IngestionStatus.SKIPPED,
                error="External/LTI resource: requires an approved provider integration",
            )
            return "external"
        if not res.local_path:
            self.resources.set_status(res.user_id, res.resource_id, IngestionStatus.PENDING,
                                      error="No local copy available (Canvas download not enabled)")
            return "external"

        path = Path(res.local_path)
        is_notebook = res.resource_type == ResourceType.FILE and path.suffix.lower() == ".ipynb"
        if res.resource_type == ResourceType.PDF:
            document_service.validate_pdf(path)
        elif res.resource_type == ResourceType.VIDEO:
            video_service.validate_video(path)
        elif is_notebook:
            document_service.validate_notebook(path)
        else:
            raise document_service.FileValidationError(f"Unsupported resource type {res.resource_type}")

        content_hash = file_sha256(path)
        if (
            not force and existing is not None and existing.content_hash == content_hash
            and existing.status == IngestionStatus.COMPLETED
        ):
            self.progress(f"Unchanged, skipping: {res.title}")
            return "skipped"

        job = self.resources.start_job(res.user_id, res.canvas_course_id, res.resource_id, res.resource_type.value)
        self.resources.set_status(res.user_id, res.resource_id, IngestionStatus.PROCESSING)
        try:
            if res.resource_type == ResourceType.PDF:
                stats = self._ingest_pdf(res, path)
            elif is_notebook:
                stats = self._ingest_notebook(res, path)
            else:
                stats = self._ingest_video(res, path, content_hash)
        except Exception as e:
            self.resources.finish_job(job, IngestionStatus.FAILED, error=str(e)[:500])
            raise
        self.resources.set_status(res.user_id, res.resource_id, IngestionStatus.COMPLETED,
                                  content_hash=content_hash, metadata={**res.metadata, **stats.get("resource_meta", {})})
        self.resources.finish_job(job, IngestionStatus.COMPLETED, stats={k: v for k, v in stats.items() if k != "resource_meta"})
        return "processed"

    # ------------------------------------------------------------------ PDF
    def _ingest_pdf(self, res: LectureResource, path: Path) -> dict:
        self.progress(f"Extracting PDF: {res.title}")
        pages = document_service.extract_pdf_pages(path)
        doc_chunks = document_service.chunk_pages(pages)
        is_deck = self._is_landscape(path)
        ctype = ContentType.SLIDE if is_deck else ContentType.PDF_PAGE
        lid = lecture_key(res.canvas_course_id, res.week, res.resource_id)
        texts = [f"{c.heading or ''}\n{c.text}" for c in doc_chunks]
        vectors = self.embedder.embed(texts) if texts else []
        chunks = [
            ContentChunk(
                chunk_id=make_chunk_id(res.resource_id, "page", f"{c.page_start}-{c.page_end}-{i}"),
                user_id=res.user_id, course_id=res.canvas_course_id, resource_id=res.resource_id,
                lecture_id=lid, content_type=ctype, text=c.text, heading=c.heading,
                module=res.module_name, week=res.week, resource_title=res.title,
                page_number=c.page_start, page_end=c.page_end, source_url=res.canvas_url,
                metadata={"embedding_model": self.embedder.name},
                embedding=vectors[i],
            )
            for i, c in enumerate(doc_chunks)
        ]
        self.vectors.replace_resource_chunks(res.user_id, res.resource_id, chunks)
        return {"pages": len(pages), "chunks": len(chunks),
                "resource_meta": {"page_count": len(pages), "deck_title": pages[0].heading if pages else None}}

    def _ingest_notebook(self, res: LectureResource, path: Path) -> dict:
        self.progress(f"Extracting notebook: {res.title}")
        sections = document_service.extract_notebook_sections(path)
        doc_chunks = document_service.chunk_pages(sections)
        lid = lecture_key(res.canvas_course_id, res.week, res.resource_id)
        vectors = self.embedder.embed([f"{c.heading or ''}\n{c.text}" for c in doc_chunks]) if doc_chunks else []
        chunks = [
            ContentChunk(
                chunk_id=make_chunk_id(res.resource_id, "cell", f"{c.page_start}-{c.page_end}-{i}"),
                user_id=res.user_id, course_id=res.canvas_course_id, resource_id=res.resource_id,
                lecture_id=lid, content_type=ContentType.NOTEBOOK, text=c.text, heading=c.heading,
                module=res.module_name, week=res.week, resource_title=res.title,
                page_number=c.page_start, page_end=c.page_end, source_url=res.canvas_url,
                metadata={"embedding_model": self.embedder.name, "unit": "cell"},
                embedding=vectors[i],
            )
            for i, c in enumerate(doc_chunks)
        ]
        self.vectors.replace_resource_chunks(res.user_id, res.resource_id, chunks)
        return {"sections": len(sections), "chunks": len(chunks), "resource_meta": {"section_count": len(sections)}}

    @staticmethod
    def _is_landscape(path: Path) -> bool:
        import pymupdf

        with pymupdf.open(path) as doc:
            if doc.page_count == 0:
                return False
            r = doc[0].rect
            return r.width > r.height

    # ------------------------------------------------------------------ video
    def _ingest_video(self, res: LectureResource, path: Path, content_hash: str) -> dict:
        self.progress(f"Transcribing video (cached after first run): {res.title}")
        segments, method = video_service.get_transcript(path, content_hash, self.transcriber)
        self.resources.replace_segments(res.user_id, res.canvas_course_id, res.resource_id, segments)
        raw_chunks = video_service.chunk_transcript(segments, embed=self.embedder.embed)
        vectors = self.embedder.embed([c["text"] for c in raw_chunks]) if raw_chunks else []

        alignments = self._align_to_slides(res, vectors)
        week = res.week
        inferred = None
        if week is None:
            inferred = self._infer_week(alignments)
            if inferred:
                week = inferred["week"]
                res.week = week
                res.module_name = res.module_name or f"Week {week}"
                self.resources.upsert(res)

        lid = lecture_key(res.canvas_course_id, week, res.resource_id)
        chunks = []
        for i, c in enumerate(raw_chunks):
            meta = {"embedding_model": self.embedder.name, "transcription": method, "segment_count": c["segment_count"]}
            if alignments[i]:
                meta["aligned_slide"] = alignments[i]
            chunks.append(
                ContentChunk(
                    chunk_id=make_chunk_id(res.resource_id, "ts", f"{c['start_time']:.2f}"),
                    user_id=res.user_id, course_id=res.canvas_course_id, resource_id=res.resource_id,
                    lecture_id=lid, content_type=ContentType.TRANSCRIPT, text=c["text"],
                    heading=(alignments[i] or {}).get("heading"), module=res.module_name, week=week,
                    resource_title=res.title, start_time=c["start_time"], end_time=c["end_time"],
                    source_url=res.canvas_url, metadata=meta, embedding=vectors[i],
                )
            )
        self.vectors.replace_resource_chunks(res.user_id, res.resource_id, chunks)
        duration = segments[-1].end_time if segments else 0
        return {
            "segments": len(segments), "chunks": len(chunks), "transcription": method,
            "aligned_chunks": sum(1 for a in alignments if a),
            "resource_meta": {"duration_seconds": duration, "transcription": method,
                              **({"week_inferred_from_slides": inferred} if inferred else {})},
        }

    def _align_to_slides(self, res: LectureResource, vectors: list[list[float]]) -> list[Optional[dict]]:
        """Map each transcript chunk to its most similar slide (same student + course only).

        This is the hook for slide/keyframe alignment: a CV keyframe matcher can later replace or
        refine this text-similarity alignment without changing the stored metadata shape.
        """
        slides = self.vectors.list_chunks(
            ChunkFilter(res.user_id, [res.canvas_course_id], content_types=[ContentType.SLIDE.value, ContentType.PDF_PAGE.value]),
            with_embedding=True,
        )
        slides = [s for s in slides if s.embedding is not None]
        if not slides or not vectors:
            return [None] * len(vectors)
        if res.week is not None:
            same_week = [s for s in slides if s.week == res.week]
            slides = same_week or slides
        mat = np.asarray([s.embedding for s in slides], dtype=np.float32)
        q = np.asarray(vectors, dtype=np.float32)
        sims = q @ mat.T
        out: list[Optional[dict]] = []
        for i in range(len(vectors)):
            j = int(np.argmax(sims[i]))
            score = float(sims[i, j])
            if score < ALIGN_MIN_SIMILARITY:
                out.append(None)
                continue
            s = slides[j]
            out.append({
                "resource_id": s.resource_id, "chunk_id": s.chunk_id, "resource_title": s.resource_title,
                "page_number": s.page_number, "page_end": s.page_end, "heading": s.heading,
                "week": s.week, "similarity": round(score, 3), "method": "text_embedding",
            })
        return out

    @staticmethod
    def _infer_week(alignments: list[Optional[dict]]) -> Optional[dict]:
        """Primary week = strict plurality of aligned slides; recordings often span two lectures,
        so other weeks with a substantial share are kept as related weeks."""
        weeks = [a["week"] for a in alignments if a and a.get("week") is not None]
        if len(weeks) < 3:
            return None
        counts = Counter(weeks).most_common()
        (week, n), runner_up = counts[0], (counts[1][1] if len(counts) > 1 else 0)
        share = n / len(weeks)
        if share < 0.3 or n == runner_up:
            return None
        related = sorted(w for w, c in counts[1:] if c / len(weeks) >= 0.2)
        return {"week": week, "share_of_aligned_chunks": round(share, 2), "aligned_chunks": len(weeks),
                "related_weeks": related}
