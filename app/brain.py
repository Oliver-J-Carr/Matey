"""The brain agent: plans, uses tools, and decides when to speak."""

from __future__ import annotations

from agents import Agent, ModelSettings, RunContextWrapper
from openai.types.shared import Reasoning

from .config import settings
from .context import MateyContext
from .prompts import BRAIN_PROMPT
from .tools import ALL_TOOLS


def _instructions(ctx: RunContextWrapper[MateyContext], agent: Agent) -> str:
    """Dynamic instructions, rebuilt before every model call.

    Two separate views avoid a "before vs after" mix-up: the workspace frozen
    at the moment the user asked, plus a log of what the tools changed since.
    """
    c = ctx.context
    changes = "\n".join(f"- {line}" for line in c.changes_this_turn) or "(none yet)"
    return (
        f"{BRAIN_PROMPT}\n\n"
        "# Workspace when the user made this request\n\n"
        f"{c.turn_start_snapshot}\n\n"
        "# Changes you have made during this request\n\n"
        f"{changes}"
    )

def build_brain_agent(model=None) -> Agent[MateyContext]:
    effort = settings.brain_reasoning_effort
    return Agent[MateyContext](
        name="Matey Brain",
        instructions=_instructions,
        tools=ALL_TOOLS,
        model=model or settings.brain_model,
        model_settings=ModelSettings(reasoning=Reasoning(effort=effort)) if effort else ModelSettings(),
    )
