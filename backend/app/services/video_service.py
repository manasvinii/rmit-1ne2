"""Lecture video -> audio -> timestamped transcript -> semantic transcript chunks.

Audio decoding is done by PyAV (bundled with faster-whisper), so no system ffmpeg is required.
Transcripts are cached by file content hash so a recording is only transcribed once.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, Optional, Protocol

from app.core.config import get_settings
from app.models.resource_models import TranscriptSegment

log = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
VIDEO_MIME_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/x-m4v"}


def validate_video(path: Path, max_mb: Optional[int] = None) -> int:
    from app.services.document_service import FileValidationError

    max_mb = get_settings().max_video_mb if max_mb is None else max_mb
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise FileValidationError(f"{path.name}: unsupported video type")
    size = path.stat().st_size
    if size > max_mb * 1024 * 1024:
        raise FileValidationError(f"{path.name}: {size / 1e6:.0f} MB exceeds limit of {max_mb} MB")
    with open(path, "rb") as f:
        head = f.read(12)
    if path.suffix.lower() in {".mp4", ".m4v", ".mov"} and head[4:8] != b"ftyp":
        raise FileValidationError(f"{path.name}: file content is not an MP4/QuickTime container")
    return size


def extract_audio(path: Path, sample_rate: int = 16000):
    """Decode the audio track to mono float32 PCM at `sample_rate` (Whisper's input format)."""
    import av
    import numpy as np

    chunks = []
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"{path.name}: no audio track")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    return (np.concatenate(chunks).astype(np.float32) / 32768.0) if chunks else np.zeros(0, np.float32)


class Transcriber(Protocol):
    name: str

    def transcribe(self, path: Path) -> list[TranscriptSegment]: ...


class FasterWhisperTranscriber:
    """Whisper (CTranslate2) speech-to-text with segment-level timestamps."""

    def __init__(self, model_size: Optional[str] = None, device: str = "auto"):
        self.model_size = model_size or get_settings().whisper_model
        self.device = device
        self.name = f"faster-whisper:{self.model_size}"
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, device=self.device, compute_type="int8")
        return self._model

    def transcribe(
        self, path: Path, progress: Optional[Callable[[float], None]] = None
    ) -> list[TranscriptSegment]:
        model = self._load()
        audio = extract_audio(path)
        segments, info = model.transcribe(
            audio, beam_size=1, vad_filter=True, condition_on_previous_text=False
        )
        out: list[TranscriptSegment] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                out.append(TranscriptSegment(start_time=round(seg.start, 2), end_time=round(seg.end, 2), text=text))
                if progress and info.duration:
                    progress(min(1.0, seg.end / info.duration))
        return out


def transcript_cache_path(content_hash: str) -> Path:
    d = Path(get_settings().media_cache_dir) / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{content_hash}.json"


def load_sidecar_transcript(video_path: Path) -> Optional[list[TranscriptSegment]]:
    """Use an existing provider transcript (.vtt/.srt/.json next to the video) if present."""
    for ext in (".json", ".vtt", ".srt"):
        p = video_path.with_suffix(ext)
        if p.exists():
            if ext == ".json":
                data = json.loads(p.read_text())
                return [TranscriptSegment(**s) for s in data]
            return parse_subtitles(p.read_text())
    return None


_TS = r"(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}"


def _to_seconds(ts: str) -> float:
    ts = ts.replace(",", ".")
    parts = [float(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def parse_subtitles(raw: str) -> list[TranscriptSegment]:
    """Parse WebVTT or SRT captions into segments."""
    segs: list[TranscriptSegment] = []
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    for block in blocks:
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            m = re.match(rf"\s*({_TS})\s*-->\s*({_TS})", ln)
            if m:
                text = " ".join(lines[i + 1 :]).strip()
                text = re.sub(r"<[^>]+>", "", text)
                if text:
                    segs.append(
                        TranscriptSegment(
                            start_time=_to_seconds(m.group(1)), end_time=_to_seconds(m.group(3)), text=text
                        )
                    )
                break
    return segs


def get_transcript(
    video_path: Path,
    content_hash: str,
    transcriber: Optional[Transcriber] = None,
    progress: Optional[Callable[[float], None]] = None,
) -> tuple[list[TranscriptSegment], str]:
    """Return (segments, method). Order: provider sidecar -> cache -> Whisper."""
    sidecar = load_sidecar_transcript(video_path)
    if sidecar:
        return sidecar, "provider_transcript"
    cache = transcript_cache_path(content_hash)
    if cache.exists():
        data = json.loads(cache.read_text())
        return [TranscriptSegment(**s) for s in data["segments"]], data.get("method", "cache")
    transcriber = transcriber or FasterWhisperTranscriber()
    log.info("Transcribing %s with %s", video_path.name, transcriber.name)
    if isinstance(transcriber, FasterWhisperTranscriber):
        segments = transcriber.transcribe(video_path, progress=progress)
    else:
        segments = transcriber.transcribe(video_path)
    cache.write_text(
        json.dumps({"method": transcriber.name, "segments": [s.model_dump() for s in segments]})
    )
    return segments, transcriber.name


def chunk_transcript(
    segments: list[TranscriptSegment],
    embed: Optional[Callable[[list[str]], list[list[float]]]] = None,
    min_seconds: float = 30.0,
    max_seconds: float = 120.0,
    max_words: int = 260,
    similarity_break: float = 0.55,
) -> list[dict]:
    """Group Whisper segments into chunks that keep exact start/end timestamps.

    A chunk closes when it is long enough and either (a) it hits the duration/word cap or
    (b) the next segment is semantically dissimilar to the running chunk (topic shift).
    """
    if not segments:
        return []
    vectors = embed([s.text for s in segments]) if embed else None

    def cos(a, b) -> float:
        num = sum(x * y for x, y in zip(a, b))
        da = sum(x * x for x in a) ** 0.5
        db = sum(y * y for y in b) ** 0.5
        return num / (da * db) if da and db else 0.0

    chunks: list[dict] = []
    cur: list[int] = []
    centroid: Optional[list[float]] = None

    def flush():
        nonlocal cur, centroid
        if cur:
            segs = [segments[i] for i in cur]
            chunks.append(
                {
                    "start_time": segs[0].start_time,
                    "end_time": segs[-1].end_time,
                    "text": " ".join(s.text for s in segs),
                    "segment_count": len(segs),
                }
            )
        cur, centroid = [], None

    for i, seg in enumerate(segments):
        if cur:
            duration = seg.end_time - segments[cur[0]].start_time
            words = sum(len(segments[j].text.split()) for j in cur) + len(seg.text.split())
            long_enough = segments[cur[-1]].end_time - segments[cur[0]].start_time >= min_seconds
            topic_shift = (
                vectors is not None
                and centroid is not None
                and long_enough
                and cos(centroid, vectors[i]) < similarity_break
            )
            if duration > max_seconds or words > max_words or topic_shift:
                flush()
        cur.append(i)
        if vectors is not None:
            v = vectors[i]
            n = len(cur)
            centroid = v if centroid is None else [(c * (n - 1) + x) / n for c, x in zip(centroid, v)]
    flush()
    return chunks


def format_timestamp(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
