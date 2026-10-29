"""Audio plumbing for latency.py: read a WAV, find where the speech ends, cut it into frames, encode G.711."""

from __future__ import annotations

import array
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

# A sample louder than this counts as speech: about -40 dBFS, well above the clips' noise floor.
SPEECH_LEVEL = 330


@dataclass
class Clip:
    path: Path
    rate: int
    samples: array.array  # PCM16, mono

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate

    @property
    def speech_end(self) -> float:
        """Seconds from the start of the clip to the last sample that holds speech."""
        for i in range(len(self.samples) - 1, -1, -1):
            if abs(self.samples[i]) > SPEECH_LEVEL:
                return (i + 1) / self.rate
        return 0.0


def load_clip(path: str | Path) -> Clip:
    path = Path(path)
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            sys.exit(f"{path}: needs 16-bit mono PCM. Try: ffmpeg -i in.wav -ac 1 -c:a pcm_s16le out.wav")
        samples = array.array("h", w.readframes(w.getnframes()))
        if sys.byteorder == "big":
            samples.byteswap()
        return Clip(path, w.getframerate(), samples)


def silence(rate: int, seconds: float) -> array.array:
    return array.array("h", bytes(2 * int(rate * seconds)))


def frames(samples: array.array, rate: int, frame_ms: int) -> list[array.array]:
    n = rate * frame_ms // 1000
    return [samples[i:i + n] for i in range(0, len(samples), n)]


def to_pcm16(frame: array.array) -> bytes:
    if sys.byteorder == "big":
        frame = array.array("h", frame)
        frame.byteswap()
    return frame.tobytes()


def to_pcmu(frame: array.array) -> bytes:
    """G.711 mu-law, the encoding a phone trunk or a Twilio media stream sends."""
    return bytes(_ulaw(s) for s in frame)


def _ulaw(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), 32635) + 0x84
    exponent = max(magnitude.bit_length() - 8, 0)
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF
