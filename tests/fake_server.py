"""A fake realtime server that answers on the same schedule as the real one, measured in audio time.

It counts the audio it receives, notices where the speech stops, and only after HANGOVER_MS more audio
has arrived does it send speech_stopped. That's the shape of the real thing: the server can't confirm the
end of a turn until it has heard some silence after it, so a client that stops streaming gets no reply.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field

import websockets

HANGOVER_MS = 500
TEXT_AFTER_MS = 100
AUDIO_AFTER_MS = 200


@dataclass
class Fake:
    hangover_ms: int = HANGOVER_MS
    text_after_ms: int = TEXT_AFTER_MS
    audio_after_ms: int = AUDIO_AFTER_MS
    error: str | None = None  # send this error instead of a reply
    session: dict = field(default_factory=dict)
    frames_after_stop: int = 0
    url: str = ""

    async def handler(self, ws):
        await ws.send(json.dumps({"type": "session.created", "session": {"model": "fake"}}))
        bytes_per_ms, heard_ms, last_loud_ms, stopped = 32, 0.0, None, False
        async for raw in ws:
            event = json.loads(raw)
            if event["type"] == "session.update":
                self.session = event["session"]
                if self.session["audio"]["input"]["format"]["type"] == "audio/pcmu":
                    bytes_per_ms = 8
                await ws.send(json.dumps({"type": "session.updated", "session": self.session}))
            elif event["type"] == "input_audio_buffer.append":
                chunk = base64.b64decode(event["audio"])
                heard_ms += len(chunk) / bytes_per_ms
                if stopped:
                    self.frames_after_stop += 1
                elif loud(chunk, bytes_per_ms):
                    if last_loud_ms is None:
                        await ws.send(json.dumps({"type": "input_audio_buffer.speech_started",
                                                  "audio_start_ms": int(heard_ms)}))
                    last_loud_ms = heard_ms
                elif last_loud_ms is not None and heard_ms - last_loud_ms >= self.hangover_ms:
                    stopped = True
                    asyncio.create_task(self.reply(ws, int(last_loud_ms)))

    async def reply(self, ws, audio_end_ms: int):
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_stopped", "audio_end_ms": audio_end_ms}))
        if self.error:
            await ws.send(json.dumps({"type": "error", "error": {"message": self.error}}))
            return
        await asyncio.sleep(self.text_after_ms / 1000)
        await ws.send(json.dumps({"type": "response.output_audio_transcript.delta", "delta": "Friday at seven "}))
        await asyncio.sleep((self.audio_after_ms - self.text_after_ms) / 1000)
        await ws.send(json.dumps({"type": "response.output_audio.delta", "delta": base64.b64encode(bytes(960)).decode()}))
        await ws.send(json.dumps({"type": "response.output_audio_transcript.delta", "delta": "works."}))
        await ws.send(json.dumps({"type": "response.done", "response": {"status": "completed"}}))

    async def __aenter__(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/v1/realtime"
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()


def loud(chunk: bytes, bytes_per_ms: int) -> bool:
    if bytes_per_ms == 8:  # mu-law: digital silence is 0xFF
        return any(b not in (0xFF, 0x7F) for b in chunk)
    return any(abs(int.from_bytes(chunk[i:i + 2], "little", signed=True)) > 330 for i in range(0, len(chunk), 2))
