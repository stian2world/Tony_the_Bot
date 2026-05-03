import numpy as np
from config import Config

try:
    import whisper
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False

# Discord sends PCM: 16-bit signed int, 48 kHz, stereo (2 ch)
_DISCORD_RATE   = 48000
_WHISPER_RATE   = 16000
_DOWNSAMPLE     = _DISCORD_RATE // _WHISPER_RATE   # = 3
_BYTES_PER_SAMPLE = 2 * 2   # int16 × 2 channels
_MIN_SECONDS    = 0.5
_MIN_BYTES      = int(_DISCORD_RATE * _BYTES_PER_SAMPLE * _MIN_SECONDS)


class Transcriber:
    def __init__(self):
        if not _WHISPER_AVAILABLE:
            print("[Transcriber] whisper not installed — voice transcription disabled.")
            self.model = None
            return
        print(f"[Transcriber] Loading whisper model '{Config.WHISPER_MODEL}'…")
        self.model = whisper.load_model(Config.WHISPER_MODEL)
        print("[Transcriber] Ready.")

    def transcribe(self, pcm_bytes: bytes) -> str:
        """Return text for a raw PCM chunk, or '' if chunk is too short."""
        if self.model is None:
            return ""
        if len(pcm_bytes) < _MIN_BYTES:
            return ""

        audio = np.frombuffer(pcm_bytes, dtype=np.int16).copy()

        # Stereo interleaved → mono average
        if audio.size % 2 == 0:
            audio = audio.reshape(-1, 2).mean(axis=1)

        # 48 kHz → 16 kHz by keeping every 3rd sample (no filter needed for speech)
        audio = audio[::_DOWNSAMPLE]

        # Normalise to float32 in [-1, 1] as Whisper expects
        audio = audio.astype(np.float32) / 32768.0

        result = self.model.transcribe(audio, language="en", fp16=False)
        return result["text"].strip()
