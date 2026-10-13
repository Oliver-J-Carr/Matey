"""Settings read from environment variables (see .env.example)."""

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    # `or default` so a blank value in .env (e.g. `BRAIN_MODEL=`) uses the default.
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    # The "brain" plans and uses tools. Needs good reasoning and tool use.
    brain_model: str = _env("BRAIN_MODEL", "gpt-5.4-mini")
    # The "voice" only rewrites plain messages as Matey. Cheap and fast is fine.
    voice_model: str = _env("VOICE_MODEL", "gpt-5.4-nano")
    # Optional reasoning effort (e.g. "low"). Blank = use the model's default.
    brain_reasoning_effort: str = _env("BRAIN_REASONING_EFFORT")
    voice_reasoning_effort: str = _env("VOICE_REASONING_EFFORT")
    # Safety net on how many model calls the brain may make in one turn.
    max_turns: int = int(_env("MAX_TURNS", "12"))
    # Name shown for each turn in the OpenAI Traces dashboard.
    trace_workflow_name: str = _env("TRACE_WORKFLOW_NAME", "Matey turn")
    # Spoken voice (ElevenLabs text-to-speech). Blank key = voice off, text only.
    elevenlabs_api_key: str = _env("ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = _env("ELEVENLABS_VOICE_ID", "PPzYpIqttlTYA83688JI")  # Pirate Marshal
    elevenlabs_model: str = _env("ELEVENLABS_MODEL", "eleven_v4_turbo")
    # Speaking speed: 1.0 is normal, ElevenLabs allows 0.7 (slower) to 1.2 (faster).
    elevenlabs_speed: float = float(_env("ELEVENLABS_SPEED", "1.1"))


settings = Settings()
