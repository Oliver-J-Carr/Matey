"""Speech-to-text: turns a spoken request into text with ElevenLabs Scribe.

Optional. With no ELEVENLABS_API_KEY, build_stt() returns None, the browser
hides the microphone and requests are typed only.
"""

from __future__ import annotations

from .config import settings

TIMEOUT_SECONDS = 15


class ElevenLabsSTT:
    def __init__(self, api_key: str, model: str, httpx_client=None) -> None:
        # Imported here so the voice-off path never loads the SDK.
        from elevenlabs.client import AsyncElevenLabs

        # httpx_client is only passed by tests, to capture requests offline.
        self.client = AsyncElevenLabs(api_key=api_key, timeout=TIMEOUT_SECONDS, httpx_client=httpx_client)
        self.model = model

    @property
    def label(self) -> str:
        return f"ElevenLabs {self.model}"

    async def transcribe(self, audio: bytes, mime: str) -> str:
        """Return what was said in the recording. Raises on API or network errors."""
        result = await self.client.speech_to_text.convert(
            model_id=self.model,
            file=("speech", audio, mime),
            # Keep tags like "(laughter)" out of the brain's input.
            tag_audio_events=False,
        )
        return (getattr(result, "text", "") or "").strip()


def build_stt() -> ElevenLabsSTT | None:
    """One per conversation, or None when no API key is set (voice input off)."""
    if not settings.elevenlabs_api_key:
        return None
    return ElevenLabsSTT(settings.elevenlabs_api_key, settings.elevenlabs_stt_model)
