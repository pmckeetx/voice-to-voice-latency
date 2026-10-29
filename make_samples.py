"""Make the caller clips in samples/ with Cartesia text-to-speech, at 16 kHz and 8 kHz.

You don't need this to run latency.py: the clips are in the repo. It's here so you can see how they were
made, or make your own. Needs CARTESIA_API_KEY.
"""

import json
import os
import urllib.request
import wave

from dotenv import load_dotenv

CALLERS = {
    # name: (Cartesia voice, what the caller says)
    "booking": ("e8e5fffb-252c-436d-b842-8879b84445b6", "Hi, I'd like to book a table for four on Friday at seven."),
    "hours": ("87286a8d-7ea7-4235-a41a-dd9fa6630feb", "Hey, what time do you close on Sundays?"),
    "refund": ("30894953-bcce-41fe-892c-15ce19c843ff",
               "I had dinner with you on Tuesday and my card was charged twice. Can you refund one of them?"),
}


def tts(key: str, voice: str, text: str, rate: int) -> bytes:
    body = {
        "model_id": "sonic-3.6",
        "transcript": text,
        "voice": {"mode": "id", "id": voice},
        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": rate},
        "language": "en",
    }
    req = urllib.request.Request("https://api.cartesia.ai/tts/bytes", data=json.dumps(body).encode(), headers={
        "X-API-Key": key, "Cartesia-Version": "2025-04-16", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main():
    load_dotenv()
    key = os.environ["CARTESIA_API_KEY"]
    os.makedirs("samples", exist_ok=True)
    for name, (voice, text) in CALLERS.items():
        for rate, suffix in ((16000, ""), (8000, "-8k")):
            path = f"samples/{name}{suffix}.wav"
            with wave.open(path, "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
                w.writeframes(tts(key, voice, text, rate))
            print(path)


if __name__ == "__main__":
    main()
