"""The voice layer: turns plain messages into Matey's pirate speech.

Keeping the persona here (and only here) means the brain stays a sober,
rule-following planner, and the pirate never "drives the computer".
"""

from __future__ import annotations

import re

from agents import Agent, ModelSettings, Runner
from openai.types.shared import Reasoning

from .config import settings
from .prompts import VOICE_PROMPT

# ElevenLabs audio tags, e.g. "[laughs]" or "[sings]": spoken delivery, not text.
# Only these reach the speech; voice.md lists exactly the same set.
AUDIO_TAGS = frozenset({
    "excited", "mischievously", "whispers", "sarcastic", "curious", "surprised", "thoughtful",
    "laughs", "chuckles", "laughs harder", "sighs", "gasps", "clears throat", "snorts", "gulps",
    "sings",
})
_TAG = re.compile(r"\[([^\[\]\n]*)\]")


def _model_settings(effort: str) -> ModelSettings:
    return ModelSettings(reasoning=Reasoning(effort=effort)) if effort else ModelSettings()


def build_voice_agent(model=None) -> Agent:
    return Agent(
        name="Matey Voice",
        instructions=VOICE_PROMPT,
        model=model or settings.voice_model,
        model_settings=_model_settings(settings.voice_reasoning_effort),
    )


async def pirate_line(voice_agent: Agent, message: str, already_said: list[str]) -> str:
    """Run the voice agent once and return Matey's line.

    The voice sees only this message and its own earlier lines, never the
    user's whole request, so it can't react to work that isn't done yet.
    """
    parts = [f"Tell the captain: {message}"]
    if already_said:
        parts.append("Your earlier lines this turn:\n" + "\n".join(f"- {s}" for s in already_said))
    result = await Runner.run(voice_agent, "\n\n".join(parts), max_turns=1)
    return keep_known_tags(str(result.final_output))


def keep_known_tags(text: str) -> str:
    """Drop any bracketed tag that isn't in AUDIO_TAGS, such as made-up stage
    directions, so it is never spoken, shown or logged as Matey's line."""
    return _tidy(_TAG.sub(lambda m: m[0] if m[1].strip().lower() in AUDIO_TAGS else " ", text))


def strip_tags(text: str) -> str:
    """Remove every bracketed tag from a line, for showing it on screen."""
    return _tidy(_TAG.sub(" ", text))


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r" ([,.!?;:])", r"\1", text)
    return text.strip(" ,;:")
