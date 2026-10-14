"""Per-connection run context, shared by tools and hooks.

The Agents SDK passes this object to every tool (via RunContextWrapper) and
every hook, but never sends it to the model. It is our "backstage" area.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agents import custom_span

from .tts import describe_error
from .voice import strip_tags
from .workspace import Workspace

# A function that pushes one JSON event down the WebSocket to the browser.
SendEvent = Callable[[dict[str, Any]], Awaitable[None]]

_event_ids = itertools.count(1)


@dataclass
class MateyContext:
    workspace: Workspace
    send: SendEvent
    voice_agent: Any = None  # the agents.Agent used by the say tool
    tts: Any = None  # text-to-speech (app.tts.ElevenLabsTTS), or None for text only
    user_message: str = ""
    # Matey's lines spoken this turn (via say), so the voice avoids repeats.
    spoken_this_turn: list[str] = field(default_factory=list)
    # say tool call id -> Matey's full line (with audio tags), for the activity feed.
    said_by_call: dict[str, str] = field(default_factory=dict)
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

    async def deliver_line(self, line: str, plain: str) -> None:
        """Send one of Matey's lines to the browser, with audio if TTS is on.
        Every say event goes through here. The bubble gets the line without
        audio tags; the spoken audio keeps them."""
        event = {"type": "say", "text": strip_tags(line), "plain": plain}
        if self.tts:
            try:
                with custom_span("ElevenLabs TTS", data={"model": self.tts.model, "chars": len(line)}):
                    audio = await self.tts.synthesize(line)
                event["audio"] = base64.b64encode(audio).decode("ascii")
            except Exception as exc:  # TTS failed: still show the line
                await self.activity("error", "Spoken voice failed, showing text only", describe_error(exc))
        await self.emit(event)

    async def ui_upsert(self, component: dict) -> None:
        await self.emit({"type": "ui", "op": "upsert", "component": component})

    async def ui_delete(self, component_id: str) -> None:
        await self.emit({"type": "ui", "op": "delete", "component_id": component_id})
