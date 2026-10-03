import json

import pytest
import requests

from app.database.academic_repository import get_academic_repo
from app.services.canvas_content import CanvasContentSync
from app.services.canvas_service import CanvasAuthError, CanvasClient, CanvasForbidden
from app.services.providers import LocalFolderProvider
from app.models.resource_models import SourceProvider

BASE = "https://canvas.test"
CID = "171223"


def _page(*links):
    return {"body": "".join(f'<a href="{BASE}/courses/{CID}/files/{fid}?verifier=SECRET&amp;wrap=1">{t}</a>'
                            for fid, t in links)}


class FakeCanvas:
    base_url = BASE

    def __init__(self):
        self.downloads = []
        self.files = {
            "1": {"display_name": "Lecture_07_NNs.pdf", "content-type": "application/pdf", "size": 10, "url": "u1"},
            "2": {"display_name": "Lecture_07_NNs_lecture_version.pdf", "content-type": "application/pdf", "size": 10, "url": "u2"},
            "3": {"display_name": "Week_07_Lab.ipynb", "content-type": "application/x-ipynb+json", "size": 10, "url": "u3"},
            "4": {"display_name": "Secret.pdf", "locked_for_user": True},
            "5": {"display_name": "huge.pdf", "size": 10**12, "url": "u5"},
            "6": {"display_name": "spec_data.csv", "size": 10, "url": "u6"},
        }

    def modules(self, course_id):
        return [{"name": "Week 7", "items": [
            {"type": "Page", "title": "Lecture 07", "page_url": "lecture-07"},
            {"type": "Page", "title": "Lab 07", "page_url": "lab-07"},
            {"type": "ExternalTool", "title": "Recording", "html_url": f"{BASE}/x"},
        ]}]

    def page(self, course_id, url):
        return {"lecture-07": _page(("1", "Slides"), ("2", ""), ("4", "Hidden"), ("5", "Big")),
                "lab-07": {"body": _page(("3", "Notebook"))["body"] + '<a href="https://scikit-learn.org/">sklearn</a>'}}[url]

    def file(self, course_id, fid):
        return self.files[fid]

    def tabs(self, course_id):
        return [{"type": "external", "label": "Echo360", "full_url": f"{BASE}/courses/{CID}/external_tools/1"},
                {"type": "internal", "label": "Grades"}]

    def download(self, url, dest, max_bytes):
        self.downloads.append(url)
        dest.write_bytes(b"%PDF-1.4 " + url.encode())
        return 10


def _sync(tmp_path, client=None):
    get_academic_repo().upsert_assignments([{
        "assignment_id": "a2", "course_id": CID, "user_id": "u1", "assignment_name": "Assessment 2",
        "description": f'<a href="{BASE}/courses/{CID}/files/6/download?verifier=SECRET">data</a>',
    }])
    client = client or FakeCanvas()
    s = CanvasContentSync("u1", CID, client=client, dest=tmp_path / "c")
    return s, s.run(), client


def test_lecture_deck_lab_and_spec_files_are_sorted_into_folders(tmp_path):
    s, summary, _ = _sync(tmp_path)
    root = tmp_path / "c"
    assert (root / "lectures" / "Lecture_07_NNs.pdf").exists()
    assert (root / "lectures" / "alternates" / "Lecture_07_NNs_lecture_version.pdf").exists()
    assert (root / "labs" / "week_07" / "Week_07_Lab.ipynb").exists()
    assert (root / "assignments" / "spec_data.csv").exists()
    assert summary["lectures_for_ingestion"] == 1 and summary["locked"] == 1
    assert summary["files_by_status"]["too_large"] == 1


def test_lti_tools_are_recorded_not_accessed_and_no_signed_urls_persist(tmp_path):
    s, summary, client = _sync(tmp_path)
    assert "Echo360" in summary["external_tools"] and "Recording" in summary["external_tools"]
    assert set(client.downloads) == {"u1", "u2", "u3", "u6"}
    raw = (tmp_path / "c" / "inventory.json").read_text() + (tmp_path / "c" / "lectures" / "manifest.json").read_text()
    assert "SECRET" not in raw and "verifier" not in raw


def test_manifest_feeds_ingestion_with_week_and_canvas_source(tmp_path):
    _sync(tmp_path)
    res = LocalFolderProvider(tmp_path / "c" / "lectures").discover("u1", CID)
    assert [r.title for r in res] == ["Lecture 07 NNs"]
    assert res[0].week == 7 and res[0].source_provider == SourceProvider.CANVAS
    assert res[0].canvas_url == f"{BASE}/courses/{CID}/files/1"


def test_second_run_skips_unchanged_files(tmp_path):
    client = FakeCanvas()
    _sync(tmp_path, client)
    client.downloads.clear()
    s = CanvasContentSync("u1", CID, client=client, dest=tmp_path / "c")
    summary = s.run()
    assert client.downloads == []
    assert summary["files_by_status"]["unchanged"] == 4


def _resp(status, body="", headers=None):
    r = requests.Response()
    r.status_code, r._content = status, body.encode()
    r.headers.update(headers or {})
    return r


def test_numbered_decks_on_learning_materials_pages_are_lectures(tmp_path):
    class Materials(FakeCanvas):
        def __init__(self):
            super().__init__()
            self.files = {
                "7": {"display_name": "cosc2669_2816_2650_week03_intro.pdf", "size": 10, "url": "u7"},
                "8": {"display_name": "Learn_LaTeX.pdf", "size": 10, "url": "u8"},
            }

        def modules(self, course_id):
            return [{"name": "Week 3", "items": [
                {"type": "Page", "title": "Week 3: Learning Materials", "page_url": "w3"}]}]

        def page(self, course_id, url):
            return _page(("7", "Week 3 slides"), ("8", "LaTeX guide"))

    s = CanvasContentSync("u1", CID, client=Materials(), dest=tmp_path / "c")
    summary = s.run()
    assert (tmp_path / "c" / "lectures" / "cosc2669_2816_2650_week03_intro.pdf").exists()
    assert (tmp_path / "c" / "resources" / "Learn_LaTeX.pdf").exists()
    assert summary["lectures_for_ingestion"] == 1
    manifest = json.loads((tmp_path / "c" / "lectures" / "manifest.json").read_text())["resources"]
    assert [(m["file"], m["week"]) for m in manifest] == [("cosc2669_2816_2650_week03_intro.pdf", 3)]


def test_sync_takes_the_students_name_from_canvas():
    from app.services.canvas_service import sync_courses_and_assignments
    from tests.conftest import create_student

    class Profiled:
        def profile(self):
            return {"id": 1, "name": "Aakash Kumar", "short_name": "Aakash Kumar"}

        def courses(self):
            return [{"id": CID, "name": "Computational Machine Learning", "course_code": "COSC2793"}]

        def assignments(self, course_id):
            return []

    create_student("u9", "s9@student.rmit.edu.au")
    out = sync_courses_and_assignments("u9", client=Profiled())
    assert out["name"] == "Aakash Kumar" and out["courses"] == 1
    assert get_academic_repo().get_user("u9")["full_name"] == "Aakash Kumar"


def test_permission_401_is_not_mistaken_for_an_expired_token():
    with pytest.raises(CanvasForbidden):
        CanvasClient._raise_for_status(_resp(401, json.dumps({"status": "unauthorized", "errors": [
            {"message": "user not authorized to perform that action"}]})))
    with pytest.raises(CanvasAuthError):
        CanvasClient._raise_for_status(_resp(401, '{"errors":[{"message":"Invalid access token."}]}'))
    with pytest.raises(CanvasAuthError):
        CanvasClient._raise_for_status(_resp(401, "", {"WWW-Authenticate": 'Bearer realm="canvas-lms"'}))
    with pytest.raises(CanvasForbidden):
        CanvasClient._raise_for_status(_resp(403))
