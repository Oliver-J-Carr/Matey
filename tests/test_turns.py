"""End-to-end turns with scripted (fake) models: no API key, no cost.

ScriptedModel is the Agents SDK's own test double. We script exactly which
tool calls the "brain" makes, then check the workspace and the events the
browser would receive.
"""

import asyncio

from agents import set_tracing_disabled
from agents.testing import ScriptedModel, assistant_message, function_call

from app.conversation import Conversation

set_tracing_disabled(True)


def _call(name, args, cid):
    return function_call(name, args, call_id=cid)


def run_turns(brain_steps, voice_lines, messages):
    events = []

    async def send(event):
        events.append(event)

    async def go():
        convo = Conversation(
            send,
            brain_model=ScriptedModel(brain_steps),
            voice_model=ScriptedModel([[assistant_message(t)] for t in voice_lines]),
        )
        for m in messages:
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