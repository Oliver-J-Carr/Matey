"""Prompt files, loaded once at import time into named constants."""

from pathlib import Path

_DIR = Path(__file__).parent


def _load(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


BRAIN_PROMPT = _load("brain")
VOICE_PROMPT = _load("voice")
