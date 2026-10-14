"""The voice layer: turns plain messages into Matey's pirate speech.

Keeping the persona here (and only here) means the brain stays a sober,
rule-following planner, and the pirate never "drives the computer".
"""

from __future__ import annotations

from agents import Agent, ModelSettings, Runner
from openai.types.shared import Reasoning

from .config import settings
from .prompts import VOICE_PROMPT


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
    return str(result.final_output).strip()
