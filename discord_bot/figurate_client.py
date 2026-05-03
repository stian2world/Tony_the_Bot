"""Fetches Tony's personality from Figurate and builds a Groq system prompt."""

import requests

FIGURATE_BASE = "https://disciplined-amazement-production.up.railway.app"


def fetch_tony_system_prompt(api_key: str, character_id: str) -> str:
    """
    Pulls Tony's character config from Figurate and returns a system prompt
    string ready to be passed to Groq.
    Falls back to a hardcoded prompt if the API is unreachable.
    """
    try:
        resp = requests.get(
            f"{FIGURATE_BASE}/api/characters",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        characters = resp.json().get("data", {}).get("characters", [])
        char = next((c for c in characters if c["id"] == character_id), None)
        if char:
            cfg = char.get("characterConfig", {})
            return _build_prompt(cfg)
    except Exception as exc:
        print(f"[Figurate] Could not fetch personality ({exc}), using fallback.")

    return _fallback_prompt()


def _build_prompt(cfg: dict) -> str:
    name          = cfg.get("name", "Tony")
    bio           = cfg.get("bio", "")
    tone          = cfg.get("tone", "warm and helpful")
    traits        = ", ".join(cfg.get("traits", []))
    speaking_style = cfg.get("speakingStyle", "clear and concise")

    return (
        f"You are {name}, a classroom support robot.\n\n"
        f"{bio}\n\n"
        f"Personality traits: {traits}.\n"
        f"Tone: {tone}.\n"
        f"Speaking style: {speaking_style}.\n\n"
        "Guidelines:\n"
        "- Keep replies under 300 words unless a longer explanation is genuinely needed.\n"
        "- If a question is course-specific and you're unsure, say so honestly and suggest "
        "the student ask their teacher.\n"
        "- Never break character. Always respond as Tony."
    )


def _fallback_prompt() -> str:
    return (
        "You are Tony, a classroom support robot built to notice moments of uncertainty "
        "and respond with quiet, respectful help. You do not judge or interrupt the learning "
        "environment. Instead, you check in gently, help students put confusion into words, "
        "and offer short, clear guidance connected to the lesson.\n\n"
        "Personality traits: grounded, patient, attentive.\n"
        "Tone: warm, steady, calm, respectful.\n"
        "Speaking style: clear and concise.\n\n"
        "Keep replies under 300 words. If unsure about something course-specific, say so "
        "and suggest the student ask their teacher. Always stay in character as Tony."
    )
