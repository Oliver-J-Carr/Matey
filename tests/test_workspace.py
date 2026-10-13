import pytest

from app.workspace import Workspace, WorkspaceError


def test_create_list_and_add_items_in_one_call():
    ws = Workspace()
    lst = ws.create_list("Shopping List", ["bananas"])
    _, added = ws.add_list_items(lst.id, ["apples", "pears", "Bananas", "  "])
    assert [i.text for i in added] == ["apples", "pears"]  # duplicate + blank skipped
    assert [i.text for i in lst.items] == ["bananas", "apples", "pears"]


def test_duplicate_list_titles_are_refused():
    ws = Workspace()
    ws.create_list("Shopping List")
    with pytest.raises(WorkspaceError):
        ws.create_list("shopping   list")


def test_remove_items_reports_missing_ids():
    ws = Workspace()
    lst = ws.create_list("Tasks", ["a", "b", "c"])
    first, second = lst.items[0].id, lst.items[1].id
    _, removed, missing = ws.remove_list_items(lst.id, [first, second, "i99"])
    assert [i.text for i in removed] == ["a", "b"]
    assert missing == ["i99"]


def test_list_tools_reject_notes_and_unknown_ids():
    ws = Workspace()
    note = ws.create_note("Call Jane back")
    with pytest.raises(WorkspaceError):
        ws.add_list_items(note.id, ["x"])
    with pytest.raises(WorkspaceError):
        ws.delete_component("list-42")


def test_snapshot_lists_ids_for_the_model():
    ws = Workspace()
    ws.create_list("Shopping List", ["bananas"])
    ws.create_note("Call Jane back")
    snap = ws.snapshot_text()
    assert 'list-1 | list | "Shopping List" | items: [i1] bananas' in snap
    assert 'note-1 | note | "Note" | text: Call Jane back' in snap

def test_update_note_in_place():
    ws = Workspace()
    note = ws.create_note("Call Jane back")
    updated, old = ws.update_note(note.id, text="Call Jane back after 5pm")
    assert updated is note and note.id == "note-1"
    assert old == "Call Jane back" and note.text == "Call Jane back after 5pm"
    with pytest.raises(WorkspaceError):
        ws.update_note(note.id)  # nothing to change
    lst = ws.create_list("Tasks")
    with pytest.raises(WorkspaceError):
        ws.update_note(lst.id, text="x")  # not a note