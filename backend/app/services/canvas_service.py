"""Canvas LMS access using the authenticated student's own (encrypted-at-rest) token.

Only documented Canvas REST endpoints are used:
  GET /api/v1/courses
  GET /api/v1/courses/:course_id/assignments
  GET /api/v1/courses/:course_id/modules?include[]=items
  GET /api/v1/courses/:course_id/files/:id
  GET /api/v1/courses/:course_id/pages/:url
  GET /api/v1/courses/:course_id/tabs
Module discovery stores *metadata only*. File downloads (canvas_content.py) use the signed `url`
returned by the Files API. LTI (ExternalTool) items and tabs are recorded as external resources
without any attempt to access the provider.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterator, Optional

import requests

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret, is_encrypted
from app.database.academic_repository import AcademicRepository, get_academic_repo
from app.models.resource_models import LectureResource, ResourceType, SourceProvider
from app.services.resource_ids import make_resource_id

log = logging.getLogger(__name__)


class CanvasError(Exception):
    pass


class CanvasAuthError(CanvasError):
    """Token missing, expired or revoked. The user must supply a new token."""


class CanvasForbidden(CanvasError):
    """The token is fine but this student may not see the item (hidden tab, locked file)."""


class CanvasClient:
    def __init__(self, token: str, base_url: Optional[str] = None, session: Optional[requests.Session] = None):
        self._token = token
        self.base_url = (base_url or get_settings().canvas_base_url).rstrip("/")
        self.session = session or requests.Session()

    def __repr__(self) -> str:  # never leak the token through repr/logging
        return f"CanvasClient(base_url={self.base_url!r})"

    def _get(self, url: str, params: Optional[dict] = None) -> requests.Response:
        resp = self.session.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            timeout=30,
        )
        self._raise_for_status(resp)
        return resp

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code == 401:
            # Canvas also answers 401 "user not authorized to perform that action" for permission
            # problems; anything else (or a WWW-Authenticate challenge) means the token is bad.
            body = (getattr(resp, "text", "") or "")[:500].lower()
            challenged = "www-authenticate" in {k.lower() for k in (getattr(resp, "headers", None) or {})}
            if not challenged and "not authorized" in body:
                raise CanvasForbidden("Canvas: not authorised to view this item")
            raise CanvasAuthError("Canvas rejected the access token (expired or revoked)")
        if resp.status_code == 403:
            raise CanvasForbidden("Canvas: access to this item is restricted for students")
        if resp.status_code >= 400:
            raise CanvasError(f"Canvas request failed with HTTP {resp.status_code}")

    def paginate(self, path: str, params: Optional[dict] = None) -> Iterator[dict]:
        """Follow Canvas `Link: rel="next"` pagination."""
        url: Optional[str] = f"{self.base_url}{path}"
        params = {"per_page": 100, **(params or {})}
        while url:
            resp = self._get(url, params=params)
            data = resp.json()
            yield from (data if isinstance(data, list) else [data])
            url = resp.links.get("next", {}).get("url")
            params = None  # the next link already carries the query string

    def courses(self) -> list[dict]:
        return list(self.paginate("/api/v1/courses"))

    def profile(self) -> dict:
        """The token owner's own user record: id, name, short_name, sortable_name."""
        return self._get(f"{self.base_url}/api/v1/users/self").json()

    def assignments(self, course_id: str) -> list[dict]:
        return list(self.paginate(f"/api/v1/courses/{course_id}/assignments"))

    def modules(self, course_id: str) -> list[dict]:
        return list(self.paginate(f"/api/v1/courses/{course_id}/modules", {"include[]": "items"}))

    def file(self, course_id: str, file_id: str) -> dict:
        return self._get(f"{self.base_url}/api/v1/courses/{course_id}/files/{file_id}").json()

    def page(self, course_id: str, page_url: str) -> dict:
        return self._get(f"{self.base_url}/api/v1/courses/{course_id}/pages/{page_url}").json()

    def tabs(self, course_id: str) -> list[dict]:
        return list(self.paginate(f"/api/v1/courses/{course_id}/tabs"))

    def download(self, url: str, dest, max_bytes: int) -> int:
        """Stream a file's signed download URL (from the Files API) to `dest`. The bearer header is
        dropped by requests if Canvas redirects to its storage host, so the token never leaves Canvas."""
        with self.session.get(url, headers={"Authorization": f"Bearer {self._token}"}, stream=True, timeout=60) as resp:
            self._raise_for_status(resp)
            written = 0
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for block in resp.iter_content(1 << 20):
                    written += len(block)
                    if written > max_bytes:
                        fh.close()
                        tmp.unlink(missing_ok=True)
                        raise CanvasError(f"File exceeds the {max_bytes // (1 << 20)} MB limit")
                    fh.write(block)
            tmp.replace(dest)
            return written


# ---------------------------------------------------------------------- token handling


def get_canvas_token(user_id: str, repo: Optional[AcademicRepository] = None) -> str:
    repo = repo or get_academic_repo()
    user = repo.get_user(user_id)
    if not user or not user.get("api_token"):
        raise CanvasAuthError("No Canvas token stored for this user")
    stored = user["api_token"]
    token = decrypt_secret(stored)
    if not token:
        raise CanvasAuthError("Stored Canvas token is unreadable; please update it")
    if not is_encrypted(stored):  # legacy plaintext row -> encrypt in place
        repo.update_user(user_id, {"api_token": encrypt_secret(token)})
    return token


def client_for_user(user_id: str) -> CanvasClient:
    return CanvasClient(get_canvas_token(user_id))


# ---------------------------------------------------------------------- course / assignment sync


def normalize_course(c: dict, user_id: str, email: Optional[str]) -> dict:
    return {
        "course_id": c.get("id"),
        "course_name": c.get("name"),
        "course_code": c.get("course_code"),
        "created_at": c.get("created_at"),
        "start_at": c.get("start_at"),
        "end_at": c.get("end_at"),
        "user_id": user_id,
        "email": email,
        "apply_assignment_group_weights": c.get("apply_assignment_group_weights"),
    }


def normalize_assignment(a: dict, course_id: Any, user_id: str) -> dict:
    return {
        "assignment_id": a.get("id"),
        "course_id": course_id,
        "assignment_name": a.get("name"),
        "description": a.get("description"),
        "due_at": a.get("due_at"),
        "created_at": a.get("created_at"),
        "points_possible": a.get("points_possible"),
        "submission_types": a.get("submission_types"),
        "html_url": a.get("html_url"),
        "user_id": user_id,
    }


def sync_courses_and_assignments(
    user_id: str, client: Optional[CanvasClient] = None, repo: Optional[AcademicRepository] = None
) -> dict:
    """Original get_courses()/get_assignments() behaviour, scoped to one user and idempotent."""
    repo = repo or get_academic_repo()
    client = client or client_for_user(user_id)
    user = repo.get_user(user_id) or {}
    name = None
    try:
        me = client.profile()
        name = (me.get("short_name") or me.get("name") or "").strip()[:120] or None
    except CanvasAuthError:
        raise
    except CanvasError as e:
        log.warning("Could not read the Canvas profile: %s", e)
    if name and name != user.get("full_name"):
        repo.update_user(user_id, {"full_name": name})
    courses = [c for c in client.courses() if c.get("id") is not None and c.get("name")]
    n_courses = repo.upsert_courses([normalize_course(c, user_id, user.get("email")) for c in courses])
    n_assign = 0
    for c in courses:
        try:
            rows = [normalize_assignment(a, c["id"], user_id) for a in client.assignments(str(c["id"]))]
            n_assign += repo.upsert_assignments(rows)
        except CanvasAuthError:
            raise
        except CanvasError as e:  # e.g. 403 on a concluded course; keep syncing the rest
            log.warning("Skipping assignments for course %s: %s", c.get("id"), e)
    return {"courses": n_courses, "assignments": n_assign, "name": name}


# ---------------------------------------------------------------------- module/resource discovery

_WEEK_RE = re.compile(r"\b(?:week|wk)\s*0?(\d{1,2})\b", re.I)
_LECTURE_RE = re.compile(r"\b(?:lecture|lec|topic)[\s_\-]*0?(\d{1,2})\b", re.I)


def infer_week(*texts: Optional[str]) -> Optional[int]:
    for t in texts:
        if t and (m := _WEEK_RE.search(t)):
            return int(m.group(1))
    return None


def infer_lecture_number(*texts: Optional[str]) -> Optional[int]:
    for t in texts:
        if t and (m := _LECTURE_RE.search(t.replace("_", " "))):
            return int(m.group(1))
    return None


def _file_resource_type(mime: Optional[str], name: str) -> ResourceType:
    name = name.lower()
    if mime == "application/pdf" or name.endswith(".pdf"):
        return ResourceType.PDF
    if (mime or "").startswith("video/") or name.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return ResourceType.VIDEO
    if name.endswith((".ppt", ".pptx")) or "presentation" in (mime or ""):
        return ResourceType.SLIDES
    if name.endswith((".vtt", ".srt")):
        return ResourceType.TRANSCRIPT
    return ResourceType.FILE


def normalize_module_item(
    item: dict, module: dict, course_id: str, user_id: str, file_meta: Optional[dict] = None
) -> Optional[LectureResource]:
    """Map one Canvas module item to a LectureResource. Returns None for non-content items."""
    kind = item.get("type")
    title = item.get("title") or ""
    module_name = module.get("name")
    week = infer_week(module_name, title)
    common = dict(
        canvas_course_id=str(course_id),
        user_id=str(user_id),
        module_id=str(module.get("id")) if module.get("id") is not None else None,
        module_name=module_name,
        title=title,
        canvas_url=item.get("html_url"),
        week=week,
        lecture_number=infer_lecture_number(title),
        source_updated_at=None,
    )
    if kind == "File":
        meta = file_meta or {}
        mime = meta.get("content-type") or meta.get("content_type")
        name = meta.get("display_name") or meta.get("filename") or title
        return LectureResource(
            resource_id=make_resource_id(user_id, course_id, "canvas", f"file:{item.get('content_id')}"),
            resource_type=_file_resource_type(mime, name),
            mime_type=mime,
            download_url=meta.get("url"),  # short-lived signed URL; never sent to the frontend
            source_provider=SourceProvider.CANVAS,
            size_bytes=meta.get("size"),
            metadata={"canvas_file_id": item.get("content_id"), "filename": name},
            **{**common, "source_updated_at": meta.get("updated_at") or meta.get("modified_at")},
        )
    if kind == "Page":
        return LectureResource(
            resource_id=make_resource_id(user_id, course_id, "canvas", f"page:{item.get('page_url')}"),
            resource_type=ResourceType.PAGE,
            mime_type="text/html",
            source_provider=SourceProvider.CANVAS,
            metadata={"page_url": item.get("page_url"), "api_url": item.get("url")},
            **common,
        )
    if kind == "ExternalUrl":
        return LectureResource(
            resource_id=make_resource_id(user_id, course_id, "canvas", f"url:{item.get('external_url')}"),
            resource_type=ResourceType.EXTERNAL_URL,
            source_provider=SourceProvider.CANVAS,
            is_external=True,
            metadata={"external_url": item.get("external_url")},
            **common,
        )
    if kind == "ExternalTool":
        # LTI launch (e.g. lecture-capture). Recorded only; ingestion requires an approved
        # provider integration (see services/providers.py), never an auth bypass.
        return LectureResource(
            resource_id=make_resource_id(user_id, course_id, "lti", f"tool:{item.get('id')}"),
            resource_type=ResourceType.EXTERNAL_TOOL,
            source_provider=SourceProvider.LTI,
            is_external=True,
            metadata={"external_url": item.get("external_url"), "content_id": item.get("content_id")},
            **common,
        )
    return None  # SubHeader, Assignment, Quiz, Discussion are handled elsewhere


def discover_course_resources(
    client: CanvasClient, course_id: str, user_id: str, fetch_file_metadata: bool = True
) -> list[LectureResource]:
    resources: list[LectureResource] = []
    for module in client.modules(course_id):
        for item in module.get("items") or []:
            meta = None
            if item.get("type") == "File" and fetch_file_metadata and item.get("content_id"):
                try:
                    meta = client.file(course_id, str(item["content_id"]))
                except CanvasAuthError:
                    raise
                except CanvasError as e:  # file hidden/locked for students
                    log.info("File metadata unavailable for item %s: %s", item.get("id"), e)
            res = normalize_module_item(item, module, course_id, user_id, meta)
            if res:
                resources.append(res)
    return resources
