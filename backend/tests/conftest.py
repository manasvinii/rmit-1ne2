"""Shared fixtures: isolated SQLite DB per test, deterministic hash embeddings, no LLM, and a
synthetic two-student course (generated PDFs + a fake MP4 with a WebVTT sidecar transcript)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

_TMP = Path(tempfile.mkdtemp(prefix="rmit1ne-tests-"))
os.environ.update({
    "APP_ENV": "test",
    "JWT_SECRET": "test-only-jwt-secret-not-used-anywhere-else-0123456789",
    "FERNET_KEY": Fernet.generate_key().decode(),
    "EMBEDDING_PROVIDER": "hash",
    "DATABASE_URL": "",
    "SUPABASE_URL": "",
    "SUPABASE_KEY": "",
    "OPENAI_API_KEY": "",
    "OPENAI_BASE_URL": "",
    "N8N_WEBHOOK_URL": "",
    "SQLITE_PATH": str(_TMP / "unused.db"),
    "MEDIA_CACHE_DIR": str(_TMP / "cache"),
    "LOCAL_CONTENT_DIR": str(_TMP / "content"),
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402
import pytest  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.database import academic_repository  # noqa: E402
from app.database.academic_repository import SqlAcademicRepository, set_academic_repo  # noqa: E402
from app.database.db import Database, set_db  # noqa: E402
from app.services.embedding_service import HashEmbedder, set_embedder  # noqa: E402
from app.services.llm_service import set_llm  # noqa: E402

COURSE = "COSC2673"
STUDENT_A = "1111111"
STUDENT_B = "2222222"
PASSWORD = "correct-horse-battery"

LECTURE_2 = [
    ("Regression", "COSC2673 Machine Learning"),
    ("Gradient Descent", "Gradient descent (GD) is an optimisation algorithm that iteratively updates the model "
     "parameters in the direction of the negative gradient of the loss function."),
    ("Loss Function", "The loss function measures how far the predictions of the model are from the true target "
     "values across all of the examples in the training data."),
    ("Learning Rate", "The learning rate controls the step size taken by gradient descent at each iteration when "
     "the parameters of the model are updated."),
]
LECTURE_3 = [
    ("Classification", "COSC2673 Machine Learning"),
    ("Revision: Gradient Descent", "Last week we saw that gradient descent minimises the loss function by "
     "repeatedly stepping in the direction of the negative gradient of the loss."),
    ("Logistic Regression", "Logistic regression is a classification model. Logistic regression uses gradient "
     "descent to minimise the log loss over the training examples in the data."),
    ("Sigmoid Function", "The sigmoid function maps any real valued score to a probability between zero and one, "
     "which logistic regression uses to predict the positive class."),
]
LECTURE_3_VTT = """WEBVTT

00:00:05.000 --> 00:00:40.000
Today we are talking about logistic regression, which is our first classification model.

00:00:40.000 --> 00:01:20.000
To train logistic regression we again use gradient descent on the log loss, just like last week.

00:01:20.000 --> 00:02:10.000
The sigmoid function squashes the score into a probability between zero and one.

00:02:10.000 --> 00:03:00.000
If the learning rate is too large gradient descent can overshoot the minimum of the loss.
"""
# Student B has private material that must never surface for student A.
PRIVATE_B = [
    ("Quantum Annealing", "COSC2673 private notes"),
    ("Zebrafish Optimisation", "Zebrafish optimisation is a secret heuristic that only student B uploaded for "
     "their own revision and nobody else should ever be able to retrieve it."),
]


def make_pdf(path: Path, slides: list[tuple[str, str]]) -> Path:
    doc = fitz.open()
    for heading, body in slides:
        page = doc.new_page(width=960, height=540)  # landscape -> slide deck
        page.insert_text((40, 70), heading, fontsize=30)
        page.insert_textbox(fitz.Rect(40, 130, 920, 500), body, fontsize=16)
    doc.save(str(path))
    doc.close()
    return path


def make_fake_mp4(path: Path) -> Path:
    # ftyp box header is enough for validation; the sidecar transcript means it is never decoded
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    return path


@pytest.fixture(autouse=True)
def db(tmp_path):
    database = Database(url="", sqlite_path=str(tmp_path / "test.db"))
    database.init_schema()
    set_db(database)
    set_academic_repo(SqlAcademicRepository(database))
    set_embedder(HashEmbedder())
    set_llm(None)
    yield database
    set_db(None)
    set_academic_repo(None)
    set_embedder(None)
    academic_repository._repo = None


def create_student(user_id: str, email: str) -> None:
    SqlAcademicRepository().create_user({
        "user_id": user_id, "full_name": f"Student {user_id}", "email": email,
        "api_token": None, "password": hash_password(PASSWORD),
    })


def auth_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def ingest_folder(user_id: str, folder: Path, course: str = COURSE):
    from app.services.ingestion_service import IngestionService
    from app.services.providers import LocalFolderProvider

    resources = LocalFolderProvider(folder).discover(user_id, course)
    return IngestionService(embedder=HashEmbedder()).ingest(resources, use_llm=False)


@pytest.fixture
def course(tmp_path):
    """Two students in the same course id; A has lectures 2-3 (+ recording), B has private notes."""
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    make_pdf(a_dir / "Lecture_2.pdf", LECTURE_2)
    make_pdf(a_dir / "Lecture_3.pdf", LECTURE_3)
    make_fake_mp4(a_dir / "Lecture_3.mp4")
    (a_dir / "Lecture_3.vtt").write_text(LECTURE_3_VTT)
    make_pdf(b_dir / "Lecture_2.pdf", PRIVATE_B)

    create_student(STUDENT_A, f"s{STUDENT_A}@student.rmit.edu.au")
    create_student(STUDENT_B, f"s{STUDENT_B}@student.rmit.edu.au")
    report_a = ingest_folder(STUDENT_A, a_dir)
    report_b = ingest_folder(STUDENT_B, b_dir)
    return {"a_dir": a_dir, "b_dir": b_dir, "report_a": report_a, "report_b": report_b}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())
