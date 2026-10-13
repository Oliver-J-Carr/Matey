"""Run hooks: turn agent lifecycle events into activity-feed entries.

RunHooks are callbacks the SDK fires as a run progresses (agent start, model
call, tool start/end). We use them to narrate what the agent is doing.
Each tool call gets one feed entry, keyed by its call id, that flips from
"running" to "done" when the tool finishes.
"""

from __future__ import annotations

import json
from typing import Any

from agents import Agent, RunContextWrapper, RunHooks

from .context import MateyContext

_ICONS = {
    "create_list": "📜",
    "create_note": "📌",
    "update_note": "✏️",
    "add_list_items": "➕",
    "remove_list_items": "➖",
    "delete_component": "🗑️",
    "say": "🗣️",
}


def _args(context: RunContextWrapper) -> dict[str, Any]:
    raw = getattr(context, "tool_arguments", None) or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _describe(tool_name: str, a: dict[str, Any]) -> str:
    items = ", ".join(a.get("items") or [])
    match tool_name:
        case "create_list":
            return f"Creating list “{a.get('title', '')}”" + (f" with {items}" if items else "")
        case "create_note":
            return f"Pinning note “{a.get('text', '')}”"
        case "update_note":
            return f"Updating note {a.get('note_id', '?')}" + (f" to “{a['text']}”" if a.get("text") else "")
        case "add_list_items":
            return f"Adding {items} to {a.get('list_id', '?')}"
        case "remove_list_items":
            return f"Removing {', '.join(a.get('item_ids') or [])} from {a.get('list_id', '?')}"
        case "delete_component":
            return f"Deleting window {a.get('component_id', '?')}"
        case "say":
            return "Passing a message to Matey's voice"
    return f"Using {tool_name}"


class ActivityHooks(RunHooks[MateyContext]):
    async def on_agent_start(self, context: RunContextWrapper[MateyContext], agent: Agent) -> None:
        await context.context.emit(
            {"type": "activity", "kind": "agent", "status": "done",
             "text": f"🧠 {agent.name} picked up the request",
             "detail": f"model: {agent.model}"}
        )

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        await context.context.emit(
            {"type": "activity", "kind": "llm", "status": "done",
             "text": f"💭 {agent.name} is reasoning", "detail": ""}
        )

    async def on_tool_start(self, context, agent, tool) -> None:
        args = _args(context)
        detail = args.get("message", "") if tool.name == "say" else json.dumps(args, ensure_ascii=False)
        await context.context.emit(
            {"type": "activity", "kind": "tool", "status": "running",
             "key": getattr(context, "tool_call_id", None),
             "text": f"{_ICONS.get(tool.name, '🛠️')} {_describe(tool.name, args)}",
             "tool": tool.name, "detail": detail}
        )

    async def on_tool_end(self, context, agent, tool, result) -> None:
        text = str(result)
        await context.context.emit(
            {"type": "activity", "kind": "tool",
             "status": "error" if text.startswith("Error") else "done",
             "key": getattr(context, "tool_call_id", None),
             "tool": tool.name, "result": text}
        )

    async def on_agent_end(self, context, agent, output) -> None:
        await context.context.emit(
            {"type": "activity", "kind": "agent", "status": "done",
             "text": f"✅ {agent.name} finished", "detail": ""}
        )
