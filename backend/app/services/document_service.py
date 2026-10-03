"""PDF / slide-deck extraction with page provenance and heading detection, plus semantic chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

PDF_MIME = "application/pdf"

# Lines that repeat on every slide and carry no content.
_BOILERPLATE = [
    re.compile(p, re.I)
    for p in (
        r"^CRICOS provider number", r"^RTO Code", r"^\d{1,3}$", r"^page \d+( of \d+)?$",
        r"^image source", r"^source:", r"^©",
    )
]
_HEADING_PREFIX = re.compile(r"^(revision|recap|quick recap|review|from last week)\s*[:\-–]\s*", re.I)


class FileValidationError(ValueError):
    pass


def validate_pdf(path: Path, max_mb: Optional[int] = None) -> int:
    max_mb = get_settings().max_pdf_mb if max_mb is None else max_mb
    if path.suffix.lower() != ".pdf":
        raise FileValidationError(f"{path.name}: not a .pdf file")
    size = path.stat().st_size
    if size > max_mb * 1024 * 1024:
        raise FileValidationError(f"{path.name}: {size / 1e6:.1f} MB exceeds limit of {max_mb} MB")
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise FileValidationError(f"{path.name}: file content is not a PDF")
    return size


@dataclass
class PageText:
    page: int  # 1-based, as printed in a PDF viewer
    heading: Optional[str]
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def validate_notebook(path: Path, max_mb: int = 20) -> int:
    if path.suffix.lower() != ".ipynb":
        raise FileValidationError(f"{path.name}: not a .ipynb notebook")
    size = path.stat().st_size
    if size > max_mb * 1024 * 1024:
        raise FileValidationError(f"{path.name}: {size / 1e6:.1f} MB exceeds limit of {max_mb} MB")
    return size


def extract_notebook_sections(path: Path, max_code_lines: int = 25) -> list[PageText]:
    """Lab notebook -> one PageText per markdown-headed section. `page` is the 1-based cell index
    where the section starts. Code is kept (truncated) because labs teach through it; outputs are
    dropped (plots, tables and tracebacks are not explanations)."""
    import json

    try:
        cells = json.loads(path.read_text(encoding="utf-8")).get("cells") or []
    except (ValueError, UnicodeDecodeError) as e:
        raise FileValidationError(f"{path.name}: not a readable notebook ({type(e).__name__})") from e
    sections: list[PageText] = []
    cur: Optional[PageText] = None
    for idx, cell in enumerate(cells, start=1):
        src = cell.get("source") or ""
        src = "".join(src) if isinstance(src, list) else str(src)
        if not src.strip():
            continue
        if cell.get("cell_type") == "markdown":
            src = re.sub(r"<[^>]+>", " ", src)
            src = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", src)
            m = re.search(r"^\s{0,3}#{1,4}\s+(.+?)\s*#*\s*$", src, re.M)
            if m:
                if cur and cur.text.strip():
                    sections.append(cur)
                cur = PageText(idx, re.sub(r"[*_`]", "", m.group(1)).strip()[:150], "")
            body = re.sub(r"^\s{0,3}#{1,4}\s+.*$", "", src, count=1, flags=re.M) if m else src
            text = "\n".join(ln.rstrip() for ln in body.splitlines() if ln.strip())
        elif cell.get("cell_type") == "code":
            lines = [ln.rstrip() for ln in src.splitlines() if ln.strip()]
            text = "\n".join(lines[:max_code_lines]) + ("\n..." if len(lines) > max_code_lines else "")
        else:
            continue
        if cur is None:
            cur = PageText(idx, None, "")
        cur.text = f"{cur.text}\n{text}".strip()
    if cur and cur.text.strip():
        sections.append(cur)
    return sections


def _is_boilerplate(line: str) -> bool:
    s = line.strip()
    return not s or any(p.search(s) for p in _BOILERPLATE)


def _clean_lines(raw: str) -> list[str]:
    lines = []
    for ln in raw.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if _is_boilerplate(ln) or ln in {"•", "▪", "➢", "-", "–"}:
            continue
        lines.append(ln)
    return lines


def _detect_heading(page) -> Optional[str]:
    """Heading = text of the largest-font line in the top 40% of the page."""
    try:
        data = page.get_text("dict")
    except Exception:
        return None
    height = page.rect.height or 1
    best: tuple[float, str] | None = None
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = re.sub(r"\s+", " ", "".join(s["text"] for s in spans)).strip()
            if _is_boilerplate(text) or len(text) > 120 or len(text) < 3:
                continue
            if line["bbox"][1] > 0.4 * height:
                continue
            size = max(s.get("size", 0) for s in spans)
            if best is None or size > best[0] + 0.5:
                best = (size, text)
    return best[1] if best else None


def extract_pdf_pages(path: Path) -> list[PageText]:
    import pymupdf

    pages: list[PageText] = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            lines = _clean_lines(page.get_text("text"))
            heading = _detect_heading(page) or (lines[0] if lines else None)
            text = "\n".join(lines)
            pages.append(PageText(page=i + 1, heading=heading, text=text))
    return pages


def canonical_heading(heading: Optional[str]) -> Optional[str]:
    """'Revision: Supervised Learning' -> 'Supervised Learning' (keeps the topic)."""
    if not heading:
        return heading
    return _HEADING_PREFIX.sub("", heading).strip() or heading


def is_recap_heading(heading: Optional[str]) -> bool:
    return bool(heading and _HEADING_PREFIX.match(heading))


@dataclass
class DocChunk:
    page_start: int
    page_end: int
    heading: Optional[str]
    text: str


def chunk_pages(
    pages: list[PageText], min_words: int = 12, max_words: int = 320
) -> list[DocChunk]:
    """Slide-aware semantic chunking.

    - One slide is the natural semantic unit.
    - Near-empty slides (title pages, section dividers like 'Quick Recap of Last Week') are
      merged forward so their text becomes context for the following slide, which keeps its
      own heading.
    - Consecutive slides sharing a heading ("... (cont.)") are merged up to max_words.
    - Very long pages are split on paragraph boundaries.
    Page numbers are always preserved as page_start/page_end.
    """
    chunks: list[DocChunk] = []
    pending: Optional[DocChunk] = None

    def same_topic(a: Optional[str], b: Optional[str]) -> bool:
        if not a or not b:
            return False
        norm = lambda h: re.sub(r"\(cont\.?\)|continued|\d+$", "", h.lower()).strip(" :-–")
        return norm(a) == norm(b)

    for p in pages:
        if not p.text.strip():
            continue
        if p.word_count > max_words:
            if pending:
                chunks.append(pending)
                pending = None
            paras, buf = re.split(r"\n(?=[A-Z•▪➢])", p.text), []
            for para in paras:
                if buf and len(" ".join(buf).split()) + len(para.split()) > max_words:
                    chunks.append(DocChunk(p.page, p.page, p.heading, "\n".join(buf)))
                    buf = []
                buf.append(para)
            if buf:
                chunks.append(DocChunk(p.page, p.page, p.heading, "\n".join(buf)))
            continue

        if pending is not None:
            small_pending = len(pending.text.split()) < min_words
            if (small_pending or same_topic(pending.heading, p.heading)) and (
                len(pending.text.split()) + p.word_count <= max_words
            ):
                heading = p.heading if small_pending and p.heading else pending.heading
                pending = DocChunk(pending.page_start, p.page, heading, pending.text + "\n\n" + p.text)
                continue
            chunks.append(pending)
        pending = DocChunk(p.page, p.page, p.heading, p.text)
    if pending:
        chunks.append(pending)
    return chunks
