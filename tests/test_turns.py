"""End-to-end turns with scripted (fake) models: no API key, no cost.

ScriptedModel is the Agents SDK's own test double. We script exactly which
tool calls the "brain" makes, then check the workspace and the events the
browser would receive.
"""

import asyncio
import base64
import dataclasses

import pytest
from agents import set_tracing_disabled
from agents.testing import ScriptedModel, assistant_message, function_call
from elevenlabs.core.api_error import ApiError

from app.conversation import Conversation

set_tracing_disabled(True)


@pytest.fixture(autouse=True)
def no_real_tts(monkeypatch):
    # Hermetic: never build a real ElevenLabs client, even if the key is set.
    monkeypatch.setattr("app.conversation.build_tts", lambda: None)
    monkeypatch.setattr("app.conversation.build_stt", lambda: None)


class FakeTTS:
    """Stands in for ElevenLabsTTS: returns fake 'audio', or raises."""
    model = "fake-tts"
    label = "Fake TTS"

    def __init__(self, fail=None):
        self.fail = fail  # an exception to raise instead of returning audio

    async def synthesize(self, text):
        if self.fail:
            raise self.fail
        return b"mp3:" + text.encode()


class FakeSTT:
    """Stands in for ElevenLabsSTT: 'hears' a set phrase, or raises."""
    model = "fake-stt"
    label = "Fake STT"

    def __init__(self, text="", fail=None):
        self.text = text
        self.fail = fail
        self.heard = []  # (audio, mime) for each call

    async def transcribe(self, audio, mime):
        self.heard.append((audio, mime))
        if self.fail:
            raise self.fail
        return self.text


def _call(name, args, cid):
    return function_call(name, args, call_id=cid)


def run_turns(brain_steps, voice_lines, messages, tts=None, stt=None):
    """A str message is typed; a bytes message is a spoken recording."""
    events = []

    async def send(event):
        events.append(event)

    async def go():
        convo = Conversation(
            send,
            brain_model=ScriptedModel(brain_steps),
            voice_model=ScriptedModel([[assistant_message(t)] for t in voice_lines]),
            tts=tts,
            stt=stt,
        )
        for m in messages:
            if isinstance(m, bytes):
                await convo.handle_voice_message(m, "audio/webm")
            else:
                await convo.handle_user_message(m)
        return convo

    convo = asyncio.run(go())
    return convo, events


def test_multi_action_turn_updates_windows_and_speaks_twice():
    brain = [
        # Turn 1: "Make a note to call Jane back"
        [_call("create_note", {"text": "Call Jane back"}, "c1")],
        [_call("say", {"message": "Made a note to call Jane back."}, "c2")],
        [assistant_message("done")],
        # Turn 2: "Add bananas and apples to my shopping list"
        [_call("create_list", {"title": "Shopping List", "items": ["bananas", "apples"]}, "c3")],
        [_call("say", {"message": "Added bananas and apples to a new Shopping List."}, "c4")],
        [assistant_message("done")],
        # Turn 3: "I called Jane back, she wants pears, add that to my list"
        [_call("add_list_items", {"list_id": "list-1", "items": ["pears"]}, "c5")],
        [_call("say", {"message": "Added pears to the Shopping List."}, "c6")],
        [_call("delete_component", {"component_id": "note-1"}, "c7")],
        [_call("say", {"message": "Removed the note to call Jane back."}, "c8")],
        [assistant_message("done")],
    ]
    voice = ["Note pinned!", "Fruit aboard!", "Pears stowed!", "Jane be sorted!"]
    convo, events = run_turns(brain, voice, [
        "Make a note to call Jane back",
        "Add bananas and apples to my shopping list",
        "I called Jane back and she wanted pears, add that to my shopping list",
    ])

    ws = convo.ctx.workspace
    assert [c.id for c in ws.components()] == ["list-1"]
    assert [i.text for i in ws.get("list-1").items] == ["bananas", "apples", "pears"]

    says = [e["text"] for e in events if e["type"] == "say"]
    assert says == voice
    assert not any("audio" in e for e in events if e["type"] == "say")  # no TTS: text only
    assert sum(e["type"] == "turn_end" for e in events) == 3
    assert any(e["type"] == "ui" and e["op"] == "delete" and e["component_id"] == "note-1" for e in events)
    # Each tool call is reported as running, then finished, under the same key.
    keys = [e.get("key") for e in events if e["type"] == "activity" and e.get("kind") == "tool"]
    assert keys.count("c5") == 2


def test_duplicate_list_is_refused_and_model_is_told_the_id():
    brain = [
        [_call("create_list", {"title": "Shopping List"}, "c1")],
        [_call("create_list", {"title": "shopping list"}, "c2")],
        [_call("say", {"message": "You already have a Shopping List."}, "c3")],
        [assistant_message("done")],
    ]
    convo, events = run_turns(brain, ["Arr, ye already have one!"], ["shopping list please, twice"])
    results = [e.get("result", "") for e in events if e.get("key") == "c2" and "result" in e]
    assert results and "Its id is list-1" in results[0]
    assert len(convo.ctx.workspace.components()) == 1


def test_plain_text_answer_is_still_voiced():
    brain = [[assistant_message("It is sunny.")]]
    _, events = run_turns(brain, ["The sun be shinin'!"], ["weather?"])
    assert [e["text"] for e in events if e["type"] == "say"] == ["The sun be shinin'!"]


def test_failure_gives_a_fallback_line_and_unlocks_input():
    brain = [RuntimeError("model down")]
    convo, events = run_turns(brain, [], ["hello"])
    assert any(e["type"] == "say" for e in events)
    assert events[-1]["type"] == "turn_end"
    assert convo.busy is False

def test_brain_sees_frozen_start_state_plus_change_log():
    from agents import RunContextWrapper
    from app.brain import _instructions

    brain = [
        [_call("create_list", {"title": "Shopping List", "items": ["potatoes", "pears"]}, "c1")],
        [_call("say", {"message": "Created a Shopping List with potatoes and pears."}, "c2")],
        [assistant_message("done")],
    ]
    convo, _ = run_turns(brain, ["Aye!"], ["add potatoes and pears to my shopping list"])
    text = _instructions(RunContextWrapper(convo.ctx), convo.brain)

    start = text.split("# Workspace when the user made this request")[1].split("# Changes")[0]
    assert "(no windows are open)" in start and "potatoes" not in start
    assert "potatoes (i1), pears (i2)" in text.split("# Changes you have made during this request")[1]

def test_update_note_keeps_the_same_window():
    brain = [
        [_call("create_note", {"text": "Call Jane back"}, "c1")],
        [_call("say", {"message": "Made a note."}, "c2")],
        [assistant_message("done")],
        [_call("update_note", {"note_id": "note-1", "text": "Call Jane back after 5pm"}, "c3")],
        [_call("say", {"message": "Updated the note."}, "c4")],
        [assistant_message("done")],
    ]
    convo, events = run_turns(brain, ["Pinned!", "Amended!"], [
        "make a note to call Jane back", "actually, after 5pm",
    ])
    notes = convo.ctx.workspace.components()
    assert [(n.id, n.text) for n in notes] == [("note-1", "Call Jane back after 5pm")]
    assert not any(e["type"] == "ui" and e["op"] == "delete" for e in events)


def test_with_tts_every_line_carries_its_audio():
    brain = [
        [_call("say", {"message": "Starting."}, "c1")],
        [_call("say", {"message": "Finished."}, "c2")],
        [assistant_message("done")],
        # Second turn: plain-text answer, voiced by the fallback path.
        [assistant_message("It is sunny.")],
    ]
    voice = ["Hoistin' sail!", "All done!", "The sun be shinin'!"]
    _, events = run_turns(brain, voice, ["do it", "weather?"], tts=FakeTTS())
    says = [e for e in events if e["type"] == "say"]
    assert [e["text"] for e in says] == voice
    assert [base64.b64decode(e["audio"]) for e in says] == [b"mp3:" + v.encode() for v in voice]


def test_tts_failure_still_shows_the_line():
    brain = [
        [_call("say", {"message": "Added pears."}, "c1")],
        [assistant_message("done")],
    ]
    err = ApiError(status_code=402, body={"detail": {"message": "Free users cannot use library voices."}})
    convo, events = run_turns(brain, ["Pears aboard!"], ["add pears"], tts=FakeTTS(fail=err))
    says = [e for e in events if e["type"] == "say"]
    assert [e["text"] for e in says] == ["Pears aboard!"] and "audio" not in says[0]
    failures = [e for e in events if e["type"] == "activity" and "Spoken voice failed" in e.get("text", "")]
    # The feed shows ElevenLabs' reason, not the SDK's bare "ApiError()".
    assert failures[0]["detail"] == "ElevenLabs error 402: Free users cannot use library voices."
    assert events[-1]["type"] == "turn_end"
    assert convo.busy is False


def test_build_tts_is_off_without_a_key(monkeypatch):
    import app.tts

    monkeypatch.setattr(app.tts, "settings", dataclasses.replace(app.tts.settings, elevenlabs_api_key=""))
    assert app.tts.build_tts() is None
    on = dataclasses.replace(app.tts.settings, elevenlabs_api_key="test-key",
                             elevenlabs_voice_id="voice-x", elevenlabs_model="model-y")
    monkeypatch.setattr(app.tts, "settings", on)
    tts = app.tts.build_tts()  # builds a client; makes no network call
    assert (tts.voice_id, tts.model) == ("voice-x", "model-y")


def test_elevenlabs_request_asks_for_the_configured_speed():
    import json

    import httpx

    from app.tts import ElevenLabsTTS

    sent = []

    def handler(request):  # stands in for ElevenLabs: records the request, returns fake audio
        sent.append(request)
        return httpx.Response(200, content=b"ID3fake", headers={"content-type": "audio/mpeg"})

    async def go(speed):
        tts = ElevenLabsTTS("test-key", "voice-x", "model-y", speed,
                            httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return await tts.synthesize("Ahoy!")

    assert asyncio.run(go(1.1)) == b"ID3fake"
    body = json.loads(sent[0].content)
    assert "/v1/text-to-speech/voice-x" in str(sent[0].url)
    assert body["model_id"] == "model-y" and body["text"] == "Ahoy!"
    assert body["voice_settings"]["speed"] == 1.1

    asyncio.run(go(1.0))  # normal speed: leave the voice's own settings alone
    assert "voice_settings" not in json.loads(sent[1].content)


def test_spoken_request_is_transcribed_then_run_as_a_turn():
    brain = [
        [_call("create_list", {"title": "Shopping List", "items": ["pears"]}, "c1")],
        [_call("say", {"message": "Added pears to a new Shopping List."}, "c2")],
        [assistant_message("done")],
    ]
    stt = FakeSTT("add pears to my shopping list")
    convo, events = run_turns(brain, ["Pears aboard!"], [b"webm-audio"], stt=stt)

    assert stt.heard == [(b"webm-audio", "audio/webm")]
    types = [e["type"] for e in events]
    assert types.index("transcript") < types.index("say")
    assert [e["text"] for e in events if e["type"] == "transcript"] == ["add pears to my shopping list"]
    assert convo.ctx.user_message == "add pears to my shopping list"
    assert [i.text for i in convo.ctx.workspace.get("list-1").items] == ["pears"]
    assert types.count("turn_end") == 1 and types[-1] == "turn_end"
    assert convo.busy is False


def test_transcription_failure_reports_why_and_unlocks_input():
    err = ApiError(status_code=401, body={"detail": {"message": "Invalid API key."}})
    convo, events = run_turns([], [], [b"webm-audio"], stt=FakeSTT(fail=err))
    failures = [e for e in events if e["type"] == "activity" and "Couldn't hear that" in e.get("text", "")]
    assert failures[0]["detail"] == "ElevenLabs error 401: Invalid API key."
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] in ("transcript", "say") for e in events)
    assert events[-1]["type"] == "turn_end"
    assert convo.busy is False


def test_silent_recording_asks_again_without_running_the_brain():
    convo, events = run_turns([], [], [b"webm-audio"], stt=FakeSTT(""))
    assert [e["text"] for e in events if e["type"] == "error"] == ["Didn't catch that. Try again?"]
    assert not any(e["type"] in ("transcript", "say") for e in events)
    assert events[-1]["type"] == "turn_end"
    assert convo.busy is False


def test_voice_message_without_speech_to_text_is_refused():
    convo, events = run_turns([], [], [b"webm-audio"])
    assert [e["type"] for e in events] == ["error", "turn_end"]
    assert convo.busy is False


def test_build_stt_is_off_without_a_key(monkeypatch):
    import app.stt

    monkeypatch.setattr(app.stt, "settings", dataclasses.replace(app.stt.settings, elevenlabs_api_key=""))
    assert app.stt.build_stt() is None
    on = dataclasses.replace(app.stt.settings, elevenlabs_api_key="test-key", elevenlabs_stt_model="model-z")
    monkeypatch.setattr(app.stt, "settings", on)
    stt = app.stt.build_stt()  # builds a client; makes no network call
    assert (stt.model, stt.label) == ("model-z", "ElevenLabs model-z")


def test_elevenlabs_transcription_request():
    import httpx

    from app.stt import ElevenLabsSTT

    sent = []

    def handler(request):  # stands in for ElevenLabs: records the request, returns a transcript
        sent.append(request)
        return httpx.Response(200, json={
            "language_code": "en", "language_probability": 1.0, "text": " add pears ", "words": [],
        })

    async def go():
        stt = ElevenLabsSTT("test-key", "scribe_v2",
                            httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return await stt.transcribe(b"webm-audio", "audio/webm")

    assert asyncio.run(go()) == "add pears"
    body = sent[0].read()
    assert sent[0].method == "POST" and "/v1/speech-to-text" in str(sent[0].url)
    assert b'name="model_id"' in body and b"scribe_v2" in body
    assert b"webm-audio" in body and b"audio/webm" in body
    assert b'name="tag_audio_events"' in body


def test_socket_advertises_voice_input_and_rejects_bad_recordings():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app).websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["transcription"] is None  # no key: no mic
        ws.send_json({"type": "voice_message", "audio": "not base64!", "mime": "audio/webm"})
        assert ws.receive_json()["type"] == "error"
        assert ws.receive_json()["type"] == "turn_end"
