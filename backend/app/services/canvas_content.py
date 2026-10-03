"""Download a course's student-visible Canvas content into a per-student folder.

Sources, all via documented endpoints and the student's own token:
  * module items: Pages (files linked in the page body), File items, ExternalUrl, ExternalTool
  * assignment descriptions already synced from Canvas (spec attachments linked in the HTML)
  * course navigation tabs (to record LTI tools such as Echo360 lecture capture)

Layout under <data>/canvas/<user_id>/<course_id>/:
  lectures/            slides and recordings to ingest (+ manifest.json with week/module/canvas_url)
  lectures/alternates/ other versions of the same lecture deck (kept, not ingested)
  labs/week_NN/        notebooks and datasets
  assignments/         files attached to assignment specs
  resources/           everything else linked from course pages
  inventory.json       every item found, including external / locked ones and why

LTI tools are never launched or scraped; they are listed as external so the student can open them.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from app.core.config import get_settings
from app.database.academic_repository import AcademicRepository, get_academic_repo
from app.services.canvas_service import (
    CanvasAuthError,
    CanvasClient,
    CanvasError,
    client_for_user,
    infer_week,
)
from app.services.resource_ids import file_sha256

log = logging.getLogger(__name__)

_FILE_LINK = re.compile(r"/courses/(\d+)/files/(\d+)")
_ANCHOR = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_IFRAME = re.compile(r'<iframe\b[^>]*src="([^"]+)"', re.I)
_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
_SLIDE_EXT = {".pdf", ".pptx", ".ppt"}
_OTHER_EXT = {".ipynb", ".csv", ".txt", ".zip", ".xlsx", ".xls", ".json", ".docx", ".doc", ".py", ".md", ".tsv"}
_INGESTIBLE = {".pdf", *_VIDEO_EXT}


@dataclass
class ContentItem:
    kind: str  # file | external_link | external_tool | page | locked
    title: str
    context: str  # page / assignment / tab the item was found on
    week: Optional[int] = None
    module: Optional[str] = None
    canvas_url: Optional[str] = None
    file_id: Optional[str] = None
    filename: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None
    role: Optional[str] = None  # lecture | alternate | lab | assignment | resource
    path: Optional[str] = None
    sha256: Optional[str] = None
    updated_at: Optional[str] = None
    status: str = "found"  # downloaded | unchanged | skipped_type | too_large | locked | external_only | error
    note: Optional[str] = None


@dataclass
class _FileRef:
    file_id: str
    link_text: str
    context: str
    week: Optional[int]
    module: Optional[str]
    origin: str  # lecture_page | lab_page | page | assignment | module_file


def content_root(user_id: str, course_id: str) -> Path:
    return Path(get_settings().media_cache_dir).parent / "canvas" / str(user_id) / str(course_id)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\- ()]+", "_", name).strip(" .") or "file"
    return name[:150]


def _origin_for_page(title: str) -> str:
    t = title.lower()
    if re.match(r"^(lecture|lec|week \d+ lecture)\b", t):
        return "lecture_page"
    if re.match(r"^(lab|tutorial|tute|workshop|practical)\b", t):
        return "lab_page"
    if re.search(r"\b(learning|lecture|class|weekly)\s+materials?\b|\bslides\b", t):
        return "materials_page"
    return "page"


# a deck named for its week/lecture, e.g. cosc2669_2816_2650_week03_intro.pdf, Lecture_07_NNs.pdf
_NUMBERED_DECK = re.compile(r"(?:^|[^a-z])(?:week|wk|lecture|lec|topic)[\s_\-]*0?\d{1,2}(?!\d)", re.I)


class CanvasContentSync:
    def __init__(self, user_id: str, course_id: str, client: Optional[CanvasClient] = None,
                 repo: Optional[AcademicRepository] = None, dest: Optional[Path] = None, progress=None):
        self.user_id, self.course_id = str(user_id), str(course_id)
        self.client = client or client_for_user(self.user_id)
        self.repo = repo or get_academic_repo()
        self.dest = Path(dest) if dest else content_root(self.user_id, self.course_id)
        self.progress = progress or (lambda m: log.info(m))
        self.items: list[ContentItem] = []
        self._refs: dict[str, _FileRef] = {}
        self._links: set[str] = set()

    # ------------------------------------------------------------------ discovery
    def _file_url(self, file_id: str) -> str:
        return f"{self.client.base_url}/courses/{self.course_id}/files/{file_id}"

    def _scan_html(self, body: str, context: str, week, module, origin: str) -> None:
        canvas_host = urlparse(self.client.base_url).netloc
        for href, inner in _ANCHOR.findall(body or ""):
            href = html.unescape(href)
            m = _FILE_LINK.search(href)
            if m and m.group(1) == self.course_id:
                self._refs.setdefault(m.group(2), _FileRef(m.group(2), _text(inner), context, week, module, origin))
            elif href.startswith("http") and urlparse(href).netloc != canvas_host and href not in self._links:
                self._links.add(href)
                self.items.append(ContentItem("external_link", _text(inner) or href, context, week, module,
                                              canvas_url=href, status="external_only"))
        for src in _IFRAME.findall(body or ""):
            src = html.unescape(src)
            if urlparse(src).netloc != canvas_host and src not in self._links:
                self._links.add(src)
                self.items.append(ContentItem("external_tool", "Embedded player", context, week, module,
                                              canvas_url=src.split("?")[0], status="external_only",
                                              note="Embedded third-party player; not accessed"))

    def discover(self) -> None:
        for module in self.client.modules(self.course_id):
            mname = module.get("name")
            for it in module.get("items") or []:
                title, kind = it.get("title") or "", it.get("type")
                week = infer_week(mname, title)
                if kind == "Page" and it.get("page_url"):
                    try:
                        page = self.client.page(self.course_id, it["page_url"])
                    except CanvasAuthError:
                        raise
                    except CanvasError as e:
                        self.items.append(ContentItem("locked", title, mname or "", week, mname,
                                                      it.get("html_url"), status="locked", note=str(e)))
                        continue
                    self.items.append(ContentItem("page", title, mname or "", week, mname, it.get("html_url"),
                                                  status="found", note=_text(page.get("body") or "")[:300] or None))
                    self._scan_html(page.get("body") or "", title, week, mname, _origin_for_page(title))
                elif kind == "File" and it.get("content_id"):
                    self._refs.setdefault(str(it["content_id"]), _FileRef(str(it["content_id"]), title, mname or "",
                                                                         week, mname, "module_file"))
                elif kind == "ExternalUrl" and it.get("external_url") not in self._links:
                    self._links.add(it.get("external_url"))
                    self.items.append(ContentItem("external_link", title, mname or "", week, mname,
                                                  it.get("external_url"), status="external_only"))
                elif kind == "ExternalTool":
                    self.items.append(ContentItem("external_tool", title, mname or "", week, mname, it.get("html_url"),
                                                  status="external_only",
                                                  note="LTI tool; open it in Canvas. Not accessed by this app."))
        for a in self.repo.list_assignments(self.user_id, self.course_id):
            name = a.get("assignment_name") or "Assignment"
            self._scan_html(a.get("description") or "", name, infer_week(name), None, "assignment")
        try:
            for t in self.client.tabs(self.course_id):
                if t.get("type") == "external" and not t.get("hidden"):
                    label = t.get("label") or "External tool"
                    note = ("Lecture recordings live here. They are not downloaded: that needs an approved "
                            "lecture-capture integration from RMIT.") if re.search(r"echo|panopto|kaltura|lecture", label, re.I) \
                        else "LTI tool; open it in Canvas. Not accessed by this app."
                    self.items.append(ContentItem("external_tool", label, "Course navigation", canvas_url=t.get("full_url")
                                                  or t.get("html_url"), status="external_only", note=note))
        except CanvasAuthError:
            raise
        except CanvasError:
            pass

    # ------------------------------------------------------------------ download
    def _role(self, ref: _FileRef, ext: str, filename: str, primaries: dict) -> str:
        if ext in _VIDEO_EXT:
            return "lecture"
        if ref.origin in ("lecture_page", "module_file") and ext in _SLIDE_EXT:
            key = (ref.context, ext)
            if "lecture_version" in filename.lower() or "annotated" in filename.lower() or key in primaries:
                return "alternate"
            primaries[key] = filename
            return "lecture"
        if ref.origin == "materials_page" and ext in _SLIDE_EXT and ref.week and _NUMBERED_DECK.search(filename):
            return "lecture"
        if ref.origin == "lab_page":
            return "lab"
        if ref.origin == "assignment":
            return "assignment"
        return "resource"

    def _folder(self, role: str, week: Optional[int]) -> Path:
        if role == "lecture":
            return self.dest / "lectures"
        if role == "alternate":
            return self.dest / "lectures" / "alternates"
        if role == "lab":
            return self.dest / "labs" / (f"week_{week:02d}" if week else "other")
        return self.dest / ("assignments" if role == "assignment" else "resources")

    def download_all(self, previous: dict) -> None:
        s = get_settings()
        primaries: dict = {}
        # lecture slides first so the "primary deck" choice is stable
        refs = sorted(self._refs.values(), key=lambda r: (r.origin != "lecture_page", r.week or 99, r.file_id))
        for ref in refs:
            item = ContentItem("file", ref.link_text or f"File {ref.file_id}", ref.context, ref.week, ref.module,
                               canvas_url=self._file_url(ref.file_id), file_id=ref.file_id)
            self.items.append(item)
            try:
                meta = self.client.file(self.course_id, ref.file_id)
            except CanvasAuthError:
                raise
            except CanvasError as e:
                item.status, item.note = "locked", str(e)
                continue
            filename = _safe_name(meta.get("display_name") or meta.get("filename") or f"file_{ref.file_id}")
            ext = Path(filename).suffix.lower()
            item.filename, item.content_type, item.size = filename, meta.get("content-type"), meta.get("size")
            item.updated_at = meta.get("updated_at")
            item.title = ref.link_text if ref.link_text and ref.link_text.lower() not in ("", "download") else filename
            if ext not in _SLIDE_EXT | _VIDEO_EXT | _OTHER_EXT:
                item.status = "skipped_type"
                continue
            item.role = self._role(ref, ext, filename, primaries)
            if meta.get("locked_for_user") or not meta.get("url"):
                item.status, item.note = "locked", meta.get("lock_explanation") and _text(meta["lock_explanation"])[:200]
                continue
            limit = (s.max_video_mb if ext in _VIDEO_EXT else s.max_pdf_mb) * (1 << 20)
            if (meta.get("size") or 0) > limit:
                item.status = "too_large"
                continue
            folder = self._folder(item.role, ref.week)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / filename
            prev = previous.get(ref.file_id) or {}
            if target.exists() and prev.get("updated_at") == meta.get("updated_at") and prev.get("path") == str(target):
                item.path, item.sha256, item.status = str(target), prev.get("sha256"), "unchanged"
                continue
            if target.exists() and prev.get("path") != str(target):
                target = folder / f"{target.stem}_{ref.file_id}{target.suffix}"
            try:
                self.client.download(meta["url"], target, limit)
            except CanvasAuthError:
                raise
            except (CanvasError, OSError) as e:
                item.status, item.note = "error", str(e)
                continue
            item.path, item.sha256, item.status = str(target), file_sha256(target), "downloaded"
            self.progress(f"Downloaded {target.relative_to(self.dest)}")

    # ------------------------------------------------------------------ outputs
    def _write_manifest(self) -> None:
        lect = self.dest / "lectures"
        lect.mkdir(parents=True, exist_ok=True)
        entries = []
        for it in self.items:
            if it.kind == "file" and it.role == "lecture" and it.path and Path(it.path).parent == lect:
                entries.append({"file": Path(it.path).name, "week": it.week, "module": it.module,
                                "canvas_url": it.canvas_url, "source": "canvas"})
        (lect / "manifest.json").write_text(json.dumps({"resources": entries}, indent=2))

    def run(self) -> dict:
        self.dest.mkdir(parents=True, exist_ok=True)
        inv_path = self.dest / "inventory.json"
        previous = {}
        if inv_path.exists():
            for it in json.loads(inv_path.read_text()).get("items", []):
                if it.get("file_id") and it.get("path"):
                    previous[it["file_id"]] = {"path": it["path"], "sha256": it.get("sha256"), "updated_at": it.get("updated_at")}
        self.progress("Reading course modules, pages and assignment specs")
        self.discover()
        self.progress(f"Found {len(self._refs)} linked files")
        self.download_all(previous)
        self._write_manifest()
        summary = self.summary()
        inv_path.write_text(json.dumps({"course_id": self.course_id, "summary": summary,
                                        "items": [asdict(i) for i in self.items]}, indent=2))
        return summary

    def summary(self) -> dict:
        files = [i for i in self.items if i.kind == "file"]
        by = lambda key: {k: sum(1 for i in files if (getattr(i, key) or "-") == k)
                          for k in sorted({getattr(i, key) or "-" for i in files})}
        return {
            "folder": str(self.dest),
            "pages_read": sum(1 for i in self.items if i.kind == "page"),
            "files": len(files),
            "files_by_status": by("status"),
            "files_by_role": by("role"),
            "lectures_for_ingestion": sum(1 for i in files if i.role == "lecture" and i.path
                                          and Path(i.path).suffix.lower() in _INGESTIBLE),
            "external_links": sum(1 for i in self.items if i.kind == "external_link"),
            "external_tools": [i.title for i in self.items if i.kind == "external_tool"],
            "locked": sum(1 for i in self.items if i.status == "locked"),
        }


def sync_course_content(user_id: str, course_id: str, **kwargs) -> dict:
    return CanvasContentSync(user_id, course_id, **kwargs).run()


def lab_notebook_resources(user_id: str, course_id: str, folder: Path) -> list:
    """Lab notebooks downloaded by the sync (labs/week_NN/*.ipynb) as ingestible resources.
    Week, title and Canvas link come from inventory.json written by the same sync."""
    from app.models.resource_models import LectureResource, ResourceType, SourceProvider
    from app.services.resource_ids import make_resource_id

    inv = folder / "inventory.json"
    items = json.loads(inv.read_text()).get("items", []) if inv.exists() else []
    out = []
    for it in items:
        path = Path(it.get("path") or "")
        if it.get("role") != "lab" or path.suffix.lower() != ".ipynb":
            continue
        if not path.is_file() and "labs" in path.parts:  # inventory written before the folder moved
            path = folder.joinpath(*path.parts[path.parts.index("labs"):])
        if not path.is_file():
            continue
        week = it.get("week")
        named = (it.get("title") or "").strip()
        label = f"Week {week} lab" if week else re.sub(r"[_-]+", " ", path.stem)
        if named and named.lower() != "jupyter notebook" and not named.lower().endswith(".ipynb"):
            label += f": {named}"
        elif named.lower().endswith(".ipynb") and re.search(r"lab[_ -](\w+)", path.stem, re.I):
            label += f": {re.search(r'lab[_ -]([A-Za-z]+)', path.stem, re.I).group(1)}"
        out.append(LectureResource(
            resource_id=make_resource_id(user_id, course_id, "canvas", f"file:{it.get('file_id') or path.name}"),
            canvas_course_id=str(course_id), user_id=str(user_id),
            module_name=it.get("module") or (f"Week {week}" if week else None),
            title=label,
            resource_type=ResourceType.FILE, mime_type="application/x-ipynb+json",
            canvas_url=it.get("canvas_url"), local_path=str(path), source_provider=SourceProvider.CANVAS,
            week=week, size_bytes=path.stat().st_size, source_updated_at=it.get("updated_at"),
            metadata={"filename": path.name, "role": "lab", "week_inferred": False},
        ))
    return out
