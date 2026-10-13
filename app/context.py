"""Per-connection run context, shared by tools and hooks.

The Agents SDK passes this object to every tool (via RunContextWrapper) and
every hook, but never sends it to the model. It is our "backstage" area.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .workspace import Workspace

# A function that pushes one JSON event down the WebSocket to the browser.
SendEvent = Callable[[dict[str, Any]], Awaitable[None]]

_event_ids = itertools.count(1)


@dataclass
class MateyContext:
    workspace: Workspace
    send: SendEvent
    voice_agent: Any = None  # the agents.Agent used by the say tool
    user_message: str = ""
    # Matey's lines spoken this turn (via say), so the voice avoids repeats.
    spoken_this_turn: list[str] = field(default_factory=list)
    # The workspace as it was when the user sent this message (frozen).
    turn_start_snapshot: str = ""
    # What the brain's tools changed during this turn, in order.
    changes_this_turn: list[str] = field(default_factory=list)
    # Serialises say() calls so replies reach the user in order.
    say_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def start_turn(self, user_message: str) -> None:
        self.user_message = user_message
        self.spoken_this_turn = []
        self.turn_start_snapshot = self.workspace.snapshot_text()
        self.changes_this_turn = []

    # ---- event helpers ---------------------------------------------------
    async def emit(self, event: dict[str, Any]) -> None:
        event.setdefault("id", next(_event_ids))
        event.setdefault("ts", time.time())
        await self.send(event)

    async def activity(self, kind: str, text: str, detail: str = "") -> None:
        """Add an entry to the browser's activity feed."""
        await self.emit({"type": "activity", "kind": kind, "text": text, "detail": detail})

    async def ui_upsert(self, component: dict) -> None:
        await self.emit({"type": "ui", "op": "upsert", "component": component})

    async def ui_delete(self, component_id: str) -> None:
        await self.emit({"type": "ui", "op": "delete", "component_id": component_id})
