"""Text-to-speech: reads Matey's lines aloud with ElevenLabs.

Optional. With no ELEVENLABS_API_KEY, build_tts() returns None and Matey
replies in text only. ("Voice" in voice.py means the persona agent; this is
the audio.)
"""

from __future__ import annotations

from .config import settings

OUTPUT_FORMAT = "mp3_44100_128"
TIMEOUT_SECONDS = 15


class ElevenLabsTTS:
    def __init__(self, api_key: str, voice_id: str, model: str, speed: float = 1.0,
                 stability: float = 0.5, similarity: float = 0.75, httpx_client=None) -> None:
        # Imported here so the voice-off path never loads the SDK.
        from elevenlabs.client import AsyncElevenLabs

        # httpx_client is only passed by tests, to capture requests offline.
        self.client = AsyncElevenLabs(api_key=api_key, timeout=TIMEOUT_SECONDS, httpx_client=httpx_client)
        self.voice_id = voice_id
        self.model = model
        self.speed = speed
        self.stability = stability
        self.similarity = similarity

    @property
    def label(self) -> str:
        return f"ElevenLabs {self.model}"

    async def synthesize(self, text: str) -> bytes:
        """Return the line as MP3 bytes. Raises on API or network errors."""
        from elevenlabs import VoiceSettings

        # Always sent in full, so every line uses the same settings instead of
        # whatever ElevenLabs fills in. Higher stability and similarity keep the
        # accent steady; speaker boost pulls each line closer to the voice.
        voice_settings = VoiceSettings(
            stability=self.stability,
            similarity_boost=self.similarity,
            use_speaker_boost=True,
            speed=self.speed,
        )
        chunks = [
            chunk async for chunk in self.client.text_to_speech.convert(
                voice_id=self.voice_id,
                text=text,
                model_id=self.model,
                output_format=OUTPUT_FORMAT,
                voice_settings=voice_settings,
            )
        ]
        return b"".join(chunks)


def describe_error(exc: Exception) -> str:
    """A readable reason for a failed TTS call. The SDK's ApiError repr is
    just "ApiError()", so pull out the status code and ElevenLabs' message."""
    status = getattr(exc, "status_code", None)
    if status is None:
        return repr(exc)
    body = getattr(exc, "body", None)
    detail = body.get("detail") if isinstance(body, dict) else None
    message = detail.get("message") if isinstance(detail, dict) else detail or body
    return f"ElevenLabs error {status}: {message}"


def build_tts() -> ElevenLabsTTS | None:
    """One per conversation, or None when no API key is set (voice off)."""
    if not settings.elevenlabs_api_key:
        return None
    return ElevenLabsTTS(
        settings.elevenlabs_api_key, settings.elevenlabs_voice_id,
        settings.elevenlabs_model, settings.elevenlabs_speed,
        settings.elevenlabs_stability, settings.elevenlabs_similarity,
    )
