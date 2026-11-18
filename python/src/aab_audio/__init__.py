"""Audio assembly and mastering. ffmpeg when present, stdlib when not.

Segments are the cache unit; a chapter master is the listening unit. Mastering is outside
the render key on purpose: changing a loudness target must never re-synthesise speech.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 24000


def write_wav(path: Path, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit mono WAV: {path}")
        return handle.readframes(handle.getnframes()), handle.getframerate()


def duration_ms(path: Path) -> int:
    if shutil.which("ffprobe"):
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(float(result.stdout.strip()) * 1000)
    with wave.open(str(path), "rb") as handle:
        return int(handle.getnframes() / handle.getframerate() * 1000)


def silence(ms: int, sample_rate: int = SAMPLE_RATE) -> bytes:
    return b"\x00\x00" * int(sample_rate * ms / 1000)


def peak_normalise(pcm: bytes, target: float = 0.72) -> bytes:
    samples = array("h")
    samples.frombytes(pcm)
    if not samples:
        return pcm
    peak = max(max(samples), -min(samples))
    if peak == 0:
        return pcm
    gain = (target * 32767) / peak
    for i, value in enumerate(samples):
        samples[i] = int(max(-32768, min(32767, value * gain)))
    return samples.tobytes()


def build_master(segment_paths: list[Path], gaps_ms: list[int], out_base: Path) -> Path:
    """Concatenate segments with their gaps and produce an AAC chapter master.

    Returns the playable file (``.m4a`` when ffmpeg is available, ``.wav`` otherwise).
    """
    if not segment_paths:
        raise ValueError("no segments to master")
    out_base.parent.mkdir(parents=True, exist_ok=True)

    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory(dir=out_base.parent) as tmp:
            tmpdir = Path(tmp)
            silence_cache: dict[int, Path] = {}
            lines: list[str] = []
            for path, gap in zip(segment_paths, gaps_ms):
                lines.append(f"file '{path.resolve()}'")
                if gap > 0:
                    if gap not in silence_cache:
                        spath = tmpdir / f"sil_{gap}.wav"
                        write_wav(spath, silence(gap))
                        silence_cache[gap] = spath
                    lines.append(f"file '{silence_cache[gap].resolve()}'")
            list_file = tmpdir / "list.txt"
            list_file.write_text("\n".join(lines))

            raw = tmpdir / "raw.wav"
            _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                  "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(raw)])

            norm = tmpdir / "norm.wav"
            _run(["ffmpeg", "-y", "-i", str(raw),
                  "-af", "highpass=f=60,lowpass=f=11000,"
                         "loudnorm=I=-19:TP=-3:LRA=11",
                  "-ar", str(SAMPLE_RATE), "-ac", "1", str(norm)])

            master = out_base.with_suffix(".m4a")
            _run(["ffmpeg", "-y", "-i", str(norm), "-c:a", "aac", "-b:a", "64k",
                  "-ar", str(SAMPLE_RATE), "-ac", "1", "-movflags", "+faststart",
                  str(master)])
            return master

    frames: list[bytes] = []
    for path, gap in zip(segment_paths, gaps_ms):
        pcm, rate = read_wav(path)
        if rate != SAMPLE_RATE:
            raise ValueError(f"unexpected sample rate {rate} in {path}")
        frames.append(pcm)
        if gap:
            frames.append(silence(gap))
    master = out_base.with_suffix(".wav")
    write_wav(master, peak_normalise(b"".join(frames)))
    return master


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-800:]}")
