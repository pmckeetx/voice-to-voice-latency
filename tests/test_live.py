"""One real turn against the real service. Skipped unless POLYAI_LIVE=1 and POLY_API_KEY are set."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

import latency  # noqa: E402
from audio import load_clip  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (os.environ.get("POLYAI_LIVE") == "1" and os.environ.get("POLY_API_KEY")),
                       reason="set POLYAI_LIVE=1 and POLY_API_KEY"),
]
URL = os.environ.get("DIALOG_REALTIME_URL", latency.DEFAULT_URL)


@pytest.mark.parametrize("clip,fmt", [("samples/booking.wav", "pcm16"), ("samples/booking-8k.wav", "pcmu")])
async def test_one_turn(clip, fmt):
    turn = await latency.measure(URL, os.environ["POLY_API_KEY"], load_clip(ROOT / clip), fmt, text_only=False)
    row = turn.row()
    assert 0 < row["turn_ms"] < row["text_ms"] <= row["audio_ms"] < 5000
    assert turn.reply.strip()
