import pytest
import requests

from app.models.resource_models import IngestionStatus, ResourceType, SourceProvider
from app.services.canvas_service import (
    CanvasAuthError,
    CanvasClient,
    infer_lecture_number,
    infer_week,
    normalize_module_item,
)

MODULE = {"id": 11, "name": "Week 7: Neural Networks"}


def test_file_item_normalized_with_week_and_signed_url_kept_server_side():
    item = {"type": "File", "title": "Lecture 7 slides", "content_id": 99, "html_url": "https://canvas/x"}
    meta = {"content-type": "application/pdf", "display_name": "Lecture_7.pdf", "url": "https://signed", "size": 10}
    res = normalize_module_item(item, MODULE, "COSC2673", "1", meta)
    assert res.resource_type == ResourceType.PDF
    assert res.week == 7 and res.module_name == MODULE["name"]
    assert res.source_provider == SourceProvider.CANVAS and not res.is_external
    assert res.download_url == "https://signed"


def test_lti_external_tool_is_marked_external_not_ingestable():
    item = {"type": "ExternalTool", "title": "Lecture recordings", "id": 5, "external_url": "https://lti.example"}
    res = normalize_module_item(item, MODULE, "COSC2673", "1")
    assert res.resource_type == ResourceType.EXTERNAL_TOOL
    assert res.is_external and res.source_provider == SourceProvider.LTI
    assert res.local_path is None and res.download_url is None


def test_external_url_and_unsupported_items():
    url = normalize_module_item({"type": "ExternalUrl", "title": "x", "external_url": "https://y"}, MODULE, "C", "1")
    assert url.is_external
    assert normalize_module_item({"type": "SubHeader", "title": "x"}, MODULE, "C", "1") is None
    assert normalize_module_item({"type": "Assignment", "title": "x"}, MODULE, "C", "1") is None


def test_week_and_lecture_inference():
    assert infer_week("Week 03 - Classification") == 3
    assert infer_week("Introduction") is None
    assert infer_lecture_number("Lecture_8") == 8


def test_external_resources_are_skipped_by_ingestion(db):
    from app.services.embedding_service import HashEmbedder
    from app.services.ingestion_service import IngestionService

    res = normalize_module_item({"type": "ExternalTool", "title": "Echo360", "id": 1}, MODULE, "C", "1")
    report = IngestionService(embedder=HashEmbedder()).ingest([res], build_graph=False)
    assert report.external == ["Echo360"] and not report.processed
    from app.database.resource_repository import ResourceRepository

    assert ResourceRepository().get("1", res.resource_id).status == IngestionStatus.SKIPPED


class _Resp:
    def __init__(self, status, data, next_url=None):
        self.status_code, self._data = status, data
        self.links = {"next": {"url": next_url}} if next_url else {}

    def json(self):
        return self._data


class _Session(requests.Session):
    def __init__(self, pages):
        super().__init__()
        self.pages, self.calls = pages, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, headers))
        return self.pages.pop(0)


def test_canvas_pagination_follows_link_header():
    s = _Session([_Resp(200, [{"id": 1}], "https://c/api/v1/courses?page=2"), _Resp(200, [{"id": 2}])])
    client = CanvasClient("tok-123", base_url="https://c", session=s)
    assert [c["id"] for c in client.courses()] == [1, 2]
    assert s.calls[1][0] == "https://c/api/v1/courses?page=2"
    assert "tok-123" not in repr(client)


def test_expired_canvas_token_raises_auth_error():
    client = CanvasClient("expired", base_url="https://c", session=_Session([_Resp(401, {})]))
    with pytest.raises(CanvasAuthError):
        client.courses()
