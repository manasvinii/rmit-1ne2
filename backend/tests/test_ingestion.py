import pytest

from app.database.resource_repository import ResourceRepository
from app.database.vector_repository import ChunkFilter, VectorRepository
from app.models.resource_models import ContentType, IngestionStatus
from app.services.document_service import FileValidationError, chunk_pages, extract_pdf_pages, validate_pdf
from app.services.video_service import (
    chunk_transcript,
    format_timestamp,
    parse_subtitles,
    validate_video,
)
from tests.conftest import COURSE, LECTURE_2, LECTURE_3_VTT, STUDENT_A, ingest_folder, make_pdf


def test_pdf_pages_keep_page_numbers_and_headings(tmp_path):
    pages = extract_pdf_pages(make_pdf(tmp_path / "Lecture_2.pdf", LECTURE_2))
    assert [p.page for p in pages] == [1, 2, 3, 4]
    assert pages[1].heading == "Gradient Descent"
    chunks = chunk_pages(pages)
    gd = next(c for c in chunks if c.heading == "Gradient Descent")
    assert gd.page_start <= 2 <= gd.page_end
    assert "negative gradient" in gd.text


def test_pdf_validation_rejects_fake_and_oversized(tmp_path):
    fake = tmp_path / "evil.pdf"
    fake.write_bytes(b"MZ not a pdf")
    with pytest.raises(FileValidationError):
        validate_pdf(fake)
    real = make_pdf(tmp_path / "ok.pdf", LECTURE_2)
    with pytest.raises(FileValidationError):
        validate_pdf(real, max_mb=0)
    with pytest.raises(FileValidationError):
        validate_pdf(tmp_path / "notes.txt")


def test_video_validation(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"\x00" * 32)
    with pytest.raises(FileValidationError):
        validate_video(bad)


def test_subtitle_parsing_preserves_timestamps():
    segs = parse_subtitles(LECTURE_3_VTT)
    assert len(segs) == 4
    assert (segs[0].start_time, segs[0].end_time) == (5.0, 40.0)
    srt = "1\n00:01:02,500 --> 00:01:10,000\nHello <b>there</b>\n"
    s = parse_subtitles(srt)[0]
    assert (s.start_time, s.end_time, s.text) == (62.5, 70.0, "Hello there")


def test_transcript_chunks_cover_segment_times():
    segs = parse_subtitles(LECTURE_3_VTT)
    chunks = chunk_transcript(segs, min_seconds=30, max_seconds=90)
    assert len(chunks) >= 2
    assert chunks[0]["start_time"] == 5.0
    assert chunks[-1]["end_time"] == 180.0
    for a, b in zip(chunks, chunks[1:]):
        assert a["end_time"] <= b["start_time"]
    assert format_timestamp(3725) == "1:02:05"


def test_ingestion_stores_page_and_timestamp_provenance(course):
    chunks = VectorRepository().list_chunks(ChunkFilter(STUDENT_A, [COURSE]))
    slides = [c for c in chunks if c.content_type == ContentType.SLIDE]
    video = [c for c in chunks if c.content_type == ContentType.TRANSCRIPT]
    assert slides and video
    assert all(c.page_number for c in slides) and all(c.week in (2, 3) for c in slides)
    assert all(c.start_time is not None and c.end_time > c.start_time for c in video)
    assert all(c.week == 3 for c in video)  # inferred from the file name / slide alignment


def test_incremental_ingestion_skips_unchanged(course):
    again = ingest_folder(STUDENT_A, course["a_dir"])
    assert not again.processed and len(again.skipped) == 3
    statuses = {r.status for r in ResourceRepository().list(STUDENT_A, COURSE)}
    assert statuses == {IngestionStatus.COMPLETED}


def test_changed_file_is_reprocessed(course):
    make_pdf(course["a_dir"] / "Lecture_2.pdf", LECTURE_2 + [("Momentum", "Momentum accumulates past gradients "
                                                              "so that gradient descent moves faster along shallow directions.")])
    again = ingest_folder(STUDENT_A, course["a_dir"])
    assert again.processed == ["Lecture 2"]
