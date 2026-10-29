"""Measure voice-to-voice latency on an OpenAI-Realtime-compatible WebSocket endpoint.

Streams a recorded caller at real speed and times, on one clock, how long after the caller stops speaking
the turn is confirmed, the first reply text arrives, and the first reply audio arrives.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass

import websockets
from dotenv import load_dotenv

from audio import Clip, frames, load_clip, silence, to_pcm16, to_pcmu

DEFAULT_URL = "wss://api.studio.poly.ai/v1/realtime"
FRAME_MS = 20
LEAD_S = 0.5  # silence before the caller speaks, so the detector hears the onset
MAX_WAIT_S = 15.0  # give up on a turn that gets no reply
INSTRUCTIONS = (
    "You answer the phone at Saltmarsh Kitchen, a restaurant open noon to 10pm every day. "
    "You can take bookings and refunds. Answer in one short sentence."
)

FORMATS = {
    # name: (session format, the clip rate it needs, frame encoder)
    "pcm16": (lambda rate: {"type": "audio/pcm", "rate": rate}, None, to_pcm16),
    "pcmu": (lambda rate: {"type": "audio/pcmu"}, 8000, to_pcmu),
}


@dataclass
class Turn:
    """Seconds on time.perf_counter(), all taken in this process."""

    rtt: float = 0.0
    speech_end: float | None = None  # the frame holding the last of the speech left this process
    speech_stopped: float | None = None
    first_text: float | None = None
    first_audio: float | None = None
    audio_end_ms: int | None = None  # where the server says the speech ended, in audio time
    speech_end_audio_ms: float | None = None  # where it really ended, in the same audio time
    reply: str = ""

    def ms(self, mark: float | None) -> float | None:
        if mark is None or self.speech_end is None:
            return None
        return round((mark - self.speech_end) * 1000)

    def row(self) -> dict:
        marker = None
        if self.audio_end_ms is not None and self.speech_end_audio_ms is not None:
            marker = round(self.audio_end_ms - self.speech_end_audio_ms)
        return {
            "turn_ms": self.ms(self.speech_stopped),
            "text_ms": self.ms(self.first_text),
            "audio_ms": self.ms(self.first_audio),
            "rtt_ms": round(self.rtt * 1000),
            "marker_ms": marker,  # how far past the real end of the speech audio_end_ms landed
        }


async def stream(ws, clip: Clip, encode, turn: Turn, done: asyncio.Event):
    """Send the clip in 20 ms frames on a fixed schedule, then silence until the reply is in."""
    lead = frames(silence(clip.rate, LEAD_S), clip.rate, FRAME_MS)
    audio = lead + frames(clip.samples, clip.rate, FRAME_MS)
    last_speech = len(lead) + int(clip.speech_end * 1000) // FRAME_MS
    turn.speech_end_audio_ms = (LEAD_S + clip.speech_end) * 1000
    quiet = silence(clip.rate, FRAME_MS / 1000)

    start = time.perf_counter()
    i = 0
    while not done.is_set():
        frame = audio[i] if i < len(audio) else quiet
        await asyncio.sleep(max(0.0, start + i * FRAME_MS / 1000 - time.perf_counter()))
        await ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(encode(frame)).decode(),
        }))
        if i == last_speech:
            turn.speech_end = time.perf_counter()
        i += 1
        if i * FRAME_MS / 1000 > LEAD_S + clip.seconds + MAX_WAIT_S:
            break


async def listen(ws, turn: Turn, done: asyncio.Event):
    """Stamp the first of each event we care about, until the reply is done."""
    async for raw in ws:
        now = time.perf_counter()
        event = json.loads(raw)
        kind = event["type"]
        if kind == "input_audio_buffer.speech_stopped" and turn.speech_stopped is None:
            turn.speech_stopped, turn.audio_end_ms = now, event.get("audio_end_ms")
        elif kind in ("response.output_audio_transcript.delta", "response.output_text.delta"):
            turn.first_text = turn.first_text or now
            turn.reply += event.get("delta", "")
        elif kind == "response.output_audio.delta":
            turn.first_audio = turn.first_audio or now
        elif kind == "response.done":
            break
        elif kind == "error":
            raise RuntimeError(event["error"].get("message", event["error"]))
    done.set()


async def measure(url: str, key: str, clip: Clip, fmt: str, text_only: bool) -> Turn:
    session_format, _, encode = FORMATS[fmt]
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {key}"}) as ws:
        assert json.loads(await ws.recv())["type"] == "session.created"
        await ws.send(json.dumps({"type": "session.update", "session": {
            "type": "realtime",
            "instructions": INSTRUCTIONS,
            "output_modalities": ["text"] if text_only else ["audio"],
            "audio": {"input": {
                "format": session_format(clip.rate),
                "turn_detection": {"type": "server_vad", "create_response": True},
            }},
        }}))
        while json.loads(await ws.recv())["type"] != "session.updated":
            pass

        turn = Turn()
        pong = await ws.ping()
        sent = time.perf_counter()
        await pong
        turn.rtt = time.perf_counter() - sent

        done = asyncio.Event()
        await asyncio.wait_for(asyncio.gather(stream(ws, clip, encode, turn, done), listen(ws, turn, done)),
                               timeout=LEAD_S + clip.seconds + MAX_WAIT_S + 5)
        return turn


def percentile(values: list[float], p: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[p - 1]


COLS = ["turn_ms", "text_ms", "audio_ms", "rtt_ms", "marker_ms"]


def percentiles(rows: list[dict]):
    for p in (50, 95):
        values = [[r[c] for r in rows if r[c] is not None] for c in COLS]
        print(f"{'p' + str(p):>4} " + " ".join(f"{round(percentile(v, p)) if v else '-':>9}" for v in values))


def report(rows: list[dict], clips: list[str]):
    """Every turn, then the percentiles over all of them, then per clip: one slow clip can own the tail."""
    print(f"{'run':>4} " + " ".join(f"{c:>9}" for c in COLS))
    for n, row in enumerate(rows, 1):
        print(f"{n:>4} " + " ".join(f"{'-' if row[c] is None else row[c]:>9}" for c in COLS))
    percentiles(rows)
    if len(set(clips)) > 1:
        for name in dict.fromkeys(clips):
            print(f"\n{name}")
            percentiles([r for r, c in zip(rows, clips) if c == name])


async def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clips", nargs="*", default=["samples/booking.wav"], help="16-bit mono WAV files")
    parser.add_argument("--runs", type=int, default=10, help="sessions per clip")
    parser.add_argument("--format", choices=FORMATS, default="pcm16", help="pcmu needs 8 kHz clips")
    parser.add_argument("--text", action="store_true", help="text replies only, no server voice")
    parser.add_argument("--url", default=os.environ.get("DIALOG_REALTIME_URL", DEFAULT_URL))
    parser.add_argument("--json", help="also write every turn to this file")
    args = parser.parse_args()

    key = os.environ.get("POLY_API_KEY") or parser.error("set POLY_API_KEY in .env or the shell")
    rows, names, turns = [], [], []
    for path in args.clips:
        clip = load_clip(path)
        if (need := FORMATS[args.format][1]) and clip.rate != need:
            parser.error(f"{path} is {clip.rate} Hz; --format {args.format} needs {need} Hz")
        for _ in range(args.runs):
            turn = await measure(args.url, key, clip, args.format, args.text)
            rows.append(turn.row())
            names.append(clip.path.name)
            turns.append({"clip": str(path), **asdict(turn), **turn.row()})
            print(f"{clip.path.name}: {turn.row()} {turn.reply!r}", flush=True)
    print()
    report(rows, names)
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w") as f:
            json.dump({"url": args.url, "format": args.format, "turns": turns}, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
