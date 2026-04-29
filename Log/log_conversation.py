#!/usr/bin/env python3
"""
log_conversation.py
Reads the current session transcript and appends the full last assistant
response turn to prompt_log.md. Called by the Stop hook in settings.json.

A "turn" = all assistant text blocks since the most recent real user message,
including text before AND after tool calls — capturing the complete response.
"""
import sys
import json
import os
import glob
from datetime import datetime

LOG_FILE = "/Users/ramonnaula/Desktop/Classroom_Bot/Tony_the_Bot/Log/prompt_log.md"
PROJECT_DIR = os.path.expanduser(
    "~/.claude/projects/-Users-ramonnaula-Desktop-Classroom-Bot-Tony-the-Bot"
)


def get_session_id():
    try:
        data = json.loads(sys.stdin.read())
        return data.get("session_id") or data.get("sessionId")
    except Exception:
        return None


def find_transcript(session_id):
    if session_id:
        path = os.path.join(PROJECT_DIR, f"{session_id}.jsonl")
        if os.path.exists(path):
            return path
    files = glob.glob(os.path.join(PROJECT_DIR, "*.jsonl"))
    if files:
        return max(files, key=os.path.getmtime)
    return None


def extract_last_turn_text(transcript_path):
    """Return the full assistant text for the most recent response turn.

    Collects every text block from every assistant entry that appears
    after the last real user message, so multi-step tool-call responses
    are logged in full rather than just the opening sentence.
    """
    entries = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return None

    # Find the index of the last real user message (string content or text blocks)
    last_user_idx = -1
    for i in range(len(entries) - 1, -1, -1):
        msg = entries[i].get("message", {})
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            last_user_idx = i
            break
        if isinstance(content, list) and any(
            c.get("type") == "text" and c.get("text", "").strip() for c in content
        ):
            last_user_idx = i
            break

    if last_user_idx == -1:
        return None

    # Gather all assistant text blocks from the turn that followed
    texts = []
    for entry in entries[last_user_idx + 1:]:
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text" and block.get("text", "").strip():
                    texts.append(block["text"].strip())
        elif isinstance(content, str) and content.strip():
            texts.append(content.strip())

    return "\n\n".join(texts) if texts else None


def append_response(text):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n**[{timestamp}] Assistant:**\n{text}\n\n---\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def main():
    session_id = get_session_id()
    transcript = find_transcript(session_id)
    if not transcript:
        return
    text = extract_last_turn_text(transcript)
    if text:
        append_response(text)


if __name__ == "__main__":
    main()
