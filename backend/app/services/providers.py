"""Where lecture resources come from.

- LocalFolderProvider (active): lecture PDFs / recordings already placed in a folder, e.g. files
  exported from Canvas by the student. Optional `manifest.json` supplies week/module/title.
- CanvasFileProvider: Canvas module discovery (metadata only, see canvas_service). Download of
  Canvas files is intentionally not wired up yet.
- LectureCaptureProvider: interface for an *approved* lecture-capture integration (e.g. an
  institution-provisioned Echo360/Kaltura/Panopto API key). Not implemented: it requires RMIT
  to grant API access; LTI launches are never scraped or replayed.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Optional, Protocol

from app.models.resource_models import LectureResource, ResourceType, SourceProvider
from app.services.canvas_service import infer_lecture_number, infer_week
from app.services.resource_ids import make_resource_id
from app.services.video_service import VIDEO_EXTENSIONS

SUPPORTED_EXTENSIONS = {".pdf", *VIDEO_EXTENSIONS}


class ResourceProvider(Protocol):
    name: str

    def discover(self, user_id: str, course_id: str) -> list[LectureResource]: ...


class LectureCaptureProvider(Protocol):
    """Contract for a future approved lecture-recording integration."""

    name: str

    def list_recordings(self, user_id: str, course_id: str) -> list[LectureResource]: ...

    def fetch_transcript(self, resource: LectureResource) -> Optional[list[dict]]:
        """Return provider captions as [{start_time, end_time, text}] if the API offers them."""
        ...

    def fetch_media(self, resource: LectureResource, dest: Path) -> Optional[Path]: ...


def _pretty_title(stem: str) -> str:
    stem = stem.replace("_", " ").replace("-", " ")
    stem = " ".join(w for w in stem.split() if not (w.startswith("(") and w.endswith(")")))
    return stem.strip() or "Untitled"


class LocalFolderProvider:
    name = "local"

    def __init__(self, root: Path, recursive: bool = False):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"Content folder not found: {self.root}")
        self.recursive = recursive

    def _manifest(self) -> dict:
        p = self.root / "manifest.json"
        if not p.exists():
            return {}
        data = json.loads(p.read_text())
        return {entry["file"]: entry for entry in data.get("resources", []) if "file" in entry}

    def discover(self, user_id: str, course_id: str) -> list[LectureResource]:
        manifest = self._manifest()
        files = self.root.rglob("*") if self.recursive else self.root.iterdir()
        out: list[LectureResource] = []
        for path in sorted(files):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            rel = str(path.relative_to(self.root))
            meta = manifest.get(rel) or manifest.get(path.name) or {}
            lecture_no = meta.get("lecture") or infer_lecture_number(path.stem)
            week = meta.get("week") or infer_week(path.stem) or lecture_no
            is_video = path.suffix.lower() in VIDEO_EXTENSIONS
            title = meta.get("title") or _pretty_title(path.stem)
            stat = path.stat()
            out.append(
                LectureResource(
                    resource_id=make_resource_id(user_id, course_id, "local", rel),
                    canvas_course_id=str(course_id),
                    user_id=str(user_id),
                    module_id=meta.get("module_id"),
                    module_name=meta.get("module") or (f"Week {week}" if week else None),
                    title=title,
                    resource_type=ResourceType.VIDEO if is_video else ResourceType.PDF,
                    mime_type=mimetypes.guess_type(path.name)[0],
                    canvas_url=meta.get("canvas_url"),
                    local_path=str(path),
                    source_provider=SourceProvider.CANVAS if meta.get("source") == "canvas" else SourceProvider.LOCAL,
                    week=week,
                    lecture_number=lecture_no,
                    size_bytes=stat.st_size,
                    source_updated_at=str(int(stat.st_mtime)),
                    metadata={"filename": path.name, "week_inferred": "week" not in meta},
                )
            )
        return out
