import io
import wave
import numpy as np
from groq import Groq
from config import Config

# Discord sends PCM: 16-bit signed int, 48 kHz, stereo (2 ch)
_DISCORD_RATE     = 48000
_BYTES_PER_SAMPLE = 2 * 2   # int16 × 2 channels
_MIN_SECONDS      = 0.5
_MIN_BYTES        = int(_DISCORD_RATE * _BYTES_PER_SAMPLE * _MIN_SECONDS)


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(_DISCORD_RATE)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


class Transcriber:
    def __init__(self):
        self._client = Groq(api_key=Config.GROQ_API_KEY)
        print("[Transcriber] Using Groq cloud Whisper. Ready.")

    def transcribe(self, pcm_bytes: bytes) -> str:
        if len(pcm_bytes) < _MIN_BYTES:
            return ""
        wav_bytes = _pcm_to_wav(pcm_bytes)
        result = self._client.audio.transcriptions.create(
            file=("audio.wav", wav_bytes),
            model="whisper-large-v3",
            language="en",
        )
        return result.text.strip()
