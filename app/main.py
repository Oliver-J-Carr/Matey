"""FastAPI entry point: serves the UI and the /ws WebSocket.

WebSocket in one line: a phone call that stays open, so either side can
talk at any time. The browser sends user messages; the server streams back
status changes, Matey's lines, window updates and activity-feed entries.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .conversation import Conversation

log = logging.getLogger("matey")
STATIC = Path(__file__).parent / "static"
# Largest spoken request accepted. The browser stops recording after 30 s,
# which is far smaller; this only guards against oversized messages.
MAX_VOICE_BYTES = 10 * 1024 * 1024

app = FastAPI(title="Matey", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "version": __version__}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()

    async def send(event: dict) -> None:
        await ws.send_json(event)

    convo = Conversation(send)
    await send({
        "type": "hello",
        "version": __version__,
        "brain_model": settings.brain_model,
        "voice_model": settings.voice_model,
        "speech": convo.ctx.tts.label if convo.ctx.tts else None,
        "transcription": convo.stt.label if convo.stt else None,
    })

    turn: asyncio.Task | None = None
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "user_message":
                # Run the turn in the background so this loop keeps listening.
                turn = asyncio.create_task(convo.handle_user_message(str(msg.get("text", ""))))
            elif msg.get("type") == "voice_message":
                audio = _decode_voice(msg.get("audio"))
                if audio is None:
                    await send({"type": "error", "text": "That recording couldn't be read."})
                    await send({"type": "turn_end"})
                    continue
                turn = asyncio.create_task(convo.handle_voice_message(audio, str(msg.get("mime") or "audio/webm")))
    except WebSocketDisconnect:
        log.info("client disconnected: %s", convo.id)
    finally:
        if turn and not turn.done():
            turn.cancel()


def _decode_voice(data) -> bytes | None:
    """The recording's bytes, or None if missing, malformed or too big."""
    if not isinstance(data, str) or not data:
        return None
    try:
        audio = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    return audio if 0 < len(audio) <= MAX_VOICE_BYTES else None
