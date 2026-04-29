import os

class Config:
    # ── Required ───────────────────────────────────────────────────────────────
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

    # Text channel where questions and answers are posted
    QUESTIONS_CHANNEL_ID: int = int(os.getenv("QUESTIONS_CHANNEL_ID", "0"))

    # ── Optional ───────────────────────────────────────────────────────────────
    # Voice channel to auto-join when a student connects (0 = disabled, use !join)
    VOICE_CHANNEL_ID: int = int(os.getenv("VOICE_CHANNEL_ID", "0"))

    # Whisper model: "tiny" (fastest, ~39MB), "base" (balanced, ~74MB)
    # "small" is too slow for Pi — stick with tiny or base
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")

    # SQLite file path
    DB_PATH: str = os.getenv("DB_PATH", "qa_questions.db")

    # How many seconds of audio to accumulate before each Whisper pass
    # Higher = less CPU load, slower trigger detection; lower = faster but heavier
    CHUNK_SECONDS: int = int(os.getenv("CHUNK_SECONDS", "5"))

    # Trigger phrases (lowercase — matched anywhere in the transcription)
    START_PHRASE: str = "i have a question"
    STOP_PHRASE: str  = "thank you"
