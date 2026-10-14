"""One conversation = one browser connection.

Holds that connection's workspace, short-term memory (session) and agents,
and runs each user message as one traced agent turn.

State is deliberately per connection and in memory only: refreshing the page
starts a fresh conversation. (Ch 3, §3.4 of the book warns that module-level
state becomes shared state once more than one client connects.)
"""

from __future__ import annotations

import uuid

from agents import Runner, SQLiteSession, custom_span, trace

from . import __version__
from .brain import build_brain_agent
from .config import settings
from .context import MateyContext, SendEvent
from .hooks import ActivityHooks
from .stt import build_stt
from .tts import build_tts, describe_error
from .voice import build_voice_agent, pirate_line
from .workspace import Workspace

FALLBACK_LINE = "Blast, me wits be tangled in the riggin'. Try that again, captain?"


class Conversation:
    def __init__(self, send: SendEvent, brain_model=None, voice_model=None, tts=None, stt=None) -> None:
        self.id = f"matey_{uuid.uuid4().hex[:12]}"
        self.brain = build_brain_agent(brain_model)
        self.ctx = MateyContext(
            workspace=Workspace(),
            send=send,
            voice_agent=build_voice_agent(voice_model),
            tts=tts if tts is not None else build_tts(),
        )
        # In-memory SQLite: remembers earlier turns of this conversation only.
        self.session = SQLiteSession(self.id)
        self.hooks = ActivityHooks()
        # Speech-to-text for the microphone, or None when voice input is off.
        self.stt = stt if stt is not None else build_stt()
        self.busy = False

    async def handle_voice_message(self, audio: bytes, mime: str) -> None:
        """Transcribe a spoken request, then run it like a typed one."""
        if not self.stt:
            await self.ctx.emit({"type": "error", "text": "Voice input is off."})
            await self.ctx.emit({"type": "turn_end"})
            return
        if self.busy:  # the UI disables the mic too; this is the backstop
            await self.ctx.emit({"type": "error", "text": "Still working on the last request."})
            return

        self.busy = True
        await self.ctx.emit({"type": "status", "state": "thinking"})
        text = ""
        try:
            # Its own small trace, grouped with this conversation's turns.
            with trace(f"{settings.trace_workflow_name} transcription", group_id=self.id,
                       metadata={"app": "matey", "version": __version__}):
                with custom_span("ElevenLabs STT", data={"model": self.stt.model, "bytes": len(audio)}):
                    text = await self.stt.transcribe(audio, mime)
        except Exception as exc:  # keep the demo alive, but show what broke
            await self.ctx.activity("error", "⚠️ Couldn't hear that", describe_error(exc))
            await self.ctx.emit({"type": "error", "text": "Couldn't transcribe that. Try again or type it."})
        else:
            if not text:
                await self.ctx.emit({"type": "error", "text": "Didn't catch that. Try again?"})
        if not text:
            self.busy = False
            await self.ctx.emit({"type": "status", "state": "idle"})
            await self.ctx.emit({"type": "turn_end"})
            return

        await self.ctx.emit({"type": "transcript", "text": text})
        await self.ctx.activity("agent", f"🎙️ Heard: {text}")
        self.busy = False  # no await before the turn takes busy again
        await self.handle_user_message(text)

    async def handle_user_message(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.busy:  # the UI disables input too; this is the backstop
            await self.ctx.emit({"type": "error", "text": "Still working on the last request."})
            return

        self.busy = True
        self.ctx.start_turn(text)
        await self.ctx.emit({"type": "status", "state": "thinking"})
        try:
            # One trace per user turn, grouped by conversation in the
            # OpenAI Traces dashboard. The voice agent's runs (inside the
            # say tool) are nested in this same trace automatically.
            with trace(
                settings.trace_workflow_name,
                group_id=self.id,
                metadata={"app": "matey", "version": __version__},
            ):
                result = await Runner.run(
                    self.brain,
                    text,
                    context=self.ctx,
                    hooks=self.hooks,
                    session=self.session,
                    max_turns=settings.max_turns,
                )
                await self._fallback_if_silent(str(result.final_output or ""))
        except Exception as exc:  # keep the demo alive, but show what broke
            await self.ctx.activity("error", "⚠️ The turn failed", repr(exc))
            await self.ctx.deliver_line(FALLBACK_LINE, "error")
        finally:
            self.busy = False
            await self.ctx.emit({"type": "status", "state": "idle"})
            await self.ctx.emit({"type": "turn_end"})

    async def _fallback_if_silent(self, final_output: str) -> None:
        """If the brain answered in plain text instead of calling say,
        still deliver that answer through Matey's voice."""
        final = final_output.strip()
        if self.ctx.spoken_this_turn or not final or final.lower().strip(". ") == "done":
            return
        await self.ctx.activity("agent", "↪️ Brain replied without say; routing through the voice", final)
        line = await pirate_line(self.ctx.voice_agent, final, [])
        await self.ctx.deliver_line(line, final)
