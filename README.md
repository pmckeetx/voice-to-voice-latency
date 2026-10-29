# voice-to-voice-latency

Measure how long a realtime voice agent takes to answer, from the moment the caller stops speaking to the
first audio of the reply. It streams a recorded caller to an OpenAI-Realtime-compatible WebSocket at real
speed and times every turn on one clock, in the client.

The walkthrough is the post: [How to measure voice-to-voice latency in a realtime voice agent](POST_URL).

```text
 run   turn_ms   text_ms  audio_ms    rtt_ms
   1       637       641       787        48
   2       667       668       814        47
 ...
 p50       682       702       860        46
 p95       736       950      1089        51
```

That's 30 turns from the three sample callers, 16 kHz PCM in and server voice out, run against
`wss://api.studio.poly.ai/v1/realtime` from the US Midwest on 29 October 2026.

`turn_ms` is when the server confirmed the end of the turn (`input_audio_buffer.speech_stopped`), `text_ms`
the first reply text, and `audio_ms` the first reply audio, each counted from the end of the caller's speech.
`rtt_ms` is a WebSocket ping, so you can tell network time from server time.

## Prerequisites

Python 3.12 or later and [uv](https://docs.astral.sh/uv/). A Dialog-RSN-1 API key: sign in at
[studio.poly.ai](https://studio.poly.ai) and create one in the **API Keys** tab.

## Set up

```bash
git clone https://github.com/pmckeetx/voice-to-voice-latency.git
cd voice-to-voice-latency
cp .env.example .env   # then paste your key after POLY_API_KEY=
uv sync
```

## Run

```bash
uv run latency.py                                   # samples/booking.wav, 10 sessions, 16 kHz PCM
uv run latency.py samples/*.wav --runs 20 --json results/run.json
uv run latency.py samples/*-8k.wav --format pcmu    # G.711 mu-law at 8 kHz, as a phone line sends it
uv run latency.py --text                            # text replies only, no server voice
```

`--url` (or `DIALOG_REALTIME_URL`) points it at any endpoint that speaks the OpenAI Realtime protocol. Bring
your own recordings as 16-bit mono WAV files; the clips in `samples/` were made with `make_samples.py`.

## Test

```bash
uv run pytest                     # offline: a fake server with a known schedule, no keys needed
POLYAI_LIVE=1 uv run pytest -m live   # one real turn per format against the real service
```

## License

Apache 2.0
