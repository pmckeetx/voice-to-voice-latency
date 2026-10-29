"""Offline tests: no keys, no network. The fake server answers on a known schedule, so the measured gaps
must come out at that schedule, within the jitter of a laptop's event loop."""

from __future__ import annotations

import array
import math
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import latency  # noqa: E402
from audio import load_clip, to_pcmu  # noqa: E402
from fake_server import Fake  # noqa: E402

TOLERANCE_MS = 60


def tone(path: Path, rate: int, seconds: float = 1.0, tail: float = 0.2) -> Path:
    """A 440 Hz tone, then digital silence: speech with a known end."""
    n = int(rate * seconds)
    samples = array.array("h", (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)))
    samples.extend([0] * int(rate * tail))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def test_speech_end_ignores_trailing_silence(tmp_path):
    clip = load_clip(tone(tmp_path / "t.wav", 16000))
    assert clip.seconds == pytest.approx(1.2)
    assert clip.speech_end == pytest.approx(1.0, abs=0.002)


def test_ulaw_matches_g711():
    assert to_pcmu(array.array("h", [0, 32767, -32768, 1000, -1000])) == bytes([0xFF, 0x80, 0x00, 0xCE, 0x4E])


def test_percentile():
    assert latency.percentile([5.0], 95) == 5.0
    assert latency.percentile([float(v) for v in range(1, 101)], 50) == pytest.approx(50.5)
    assert latency.percentile([float(v) for v in range(1, 101)], 95) == pytest.approx(95.05)


@pytest.mark.parametrize("fmt,rate", [("pcm16", 16000), ("pcmu", 8000)])
async def test_measures_the_fake_servers_schedule(tmp_path, fmt, rate):
    clip = load_clip(tone(tmp_path / "t.wav", rate))
    async with Fake() as fake:
        turn = await latency.measure(fake.url, "test-key", clip, fmt, text_only=False)

    row = turn.row()
    assert row["turn_ms"] == pytest.approx(fake.hangover_ms, abs=TOLERANCE_MS)
    assert row["text_ms"] == pytest.approx(fake.hangover_ms + fake.text_after_ms, abs=TOLERANCE_MS)
    assert row["audio_ms"] == pytest.approx(fake.hangover_ms + fake.audio_after_ms, abs=TOLERANCE_MS)
    assert turn.reply == "Friday at seven works."
    assert turn.audio_end_ms == pytest.approx(500 + 1000, abs=40)  # lead silence plus the tone
    assert fake.session["audio"]["input"]["format"]["type"] == {"pcm16": "audio/pcm", "pcmu": "audio/pcmu"}[fmt]
    assert fake.session["output_modalities"] == ["audio"]


async def test_keeps_streaming_silence_until_the_reply(tmp_path):
    clip = load_clip(tone(tmp_path / "t.wav", 16000, tail=0.0))  # the clip itself ends with the speech
    async with Fake() as fake:
        await latency.measure(fake.url, "test-key", clip, "pcm16", text_only=True)
    assert fake.frames_after_stop > 0
    assert fake.session["output_modalities"] == ["text"]


async def test_server_error_is_raised(tmp_path):
    clip = load_clip(tone(tmp_path / "t.wav", 16000))
    async with Fake(error="rate limit") as fake:
        with pytest.raises(RuntimeError, match="rate limit"):
            await latency.measure(fake.url, "test-key", clip, "pcm16", text_only=False)
