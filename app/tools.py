"""Tools the brain agent can call.

Each tool changes the workspace (the "logbook"), pushes the change to the
browser, and returns a short plain-English result to the model. Errors are
returned as text (not raised) so the model can read them and recover.

Docstrings matter: the SDK sends them to the model as tool descriptions.
"""

from __future__ import annotations

from agents import RunContextWrapper, function_tool

from .context import MateyContext
from .voice import pirate_line
from .workspace import WorkspaceError

Ctx = RunContextWrapper[MateyContext]

def _record(ctx: Ctx, summary: str) -> str:
    """Log a successful change for this turn, then return it as the tool result."""
    ctx.context.changes_this_turn.append(summary)
    return summary

def _fmt_items(items) -> str:
    return ", ".join(f"{i.text} ({i.id})" for i in items) or "none"


@function_tool
async def create_list(ctx: Ctx, title: str, items: list[str] | None = None) -> str:
    """Create a new list window, optionally with starting items.

    Only use this when no suitable list already exists in the current workspace.

    Args:
        title: Short title in title case, e.g. "Shopping List" or "Task List".
        items: Optional items to start the list with, e.g. ["bananas", "apples"].
    """
    ws = ctx.context.workspace
    try:
        component = ws.create_list(title, items or [])
    except WorkspaceError as exc:
        existing = ws.find_list_by_title(title)
        hint = f" Its id is {existing.id}." if existing else ""
        return f"Error: {exc}{hint}"
    await ctx.context.ui_upsert(component.to_dict())
    return _record(ctx, (
        f"Created list '{component.title}' with id {component.id}. "
        f"Items: {_fmt_items(component.items)}."
    ))


@function_tool
async def create_note(ctx: Ctx, text: str, title: str = "Note") -> str:
    """Create a sticky-note window holding a short reminder.

    Args:
        text: The reminder itself, e.g. "Call Jane back".
        title: Optional short heading for the note. Defaults to "Note".
    """
    component = ctx.context.workspace.create_note(text, title)
    await ctx.context.ui_upsert(component.to_dict())
    return _record(ctx, f"Created note {component.id}: '{component.text}'.")


@function_tool
async def update_note(ctx: Ctx, note_id: str, text: str | None = None, title: str | None = None) -> str:
    """Change the wording or heading of an existing note, keeping the same window.

    Use this instead of deleting and recreating a note. Pass the full new text,
    not just the changed words.

    Args:
        note_id: Id of the note to update, e.g. "note-1".
        text: Optional full replacement text, e.g. "Call Jane back after 5pm".
        title: Optional new heading for the note.
    """
    try:
        component, old_text = ctx.context.workspace.update_note(note_id, text, title)
    except WorkspaceError as exc:
        return f"Error: {exc}"
    await ctx.context.ui_upsert(component.to_dict())
    return _record(
        ctx, f"Updated note {component.id}: '{old_text}' is now '{component.text}'."
    )


@function_tool
async def add_list_items(ctx: Ctx, list_id: str, items: list[str]) -> str:
    """Add one or more items to an existing list in a single call.

    Args:
        list_id: Id of the list to add to, e.g. "list-1".
        items: All the items to add, e.g. ["bananas", "apples"]. Duplicates are skipped.
    """
    try:
        component, added = ctx.context.workspace.add_list_items(list_id, items)
    except WorkspaceError as exc:
        return f"Error: {exc}"
    await ctx.context.ui_upsert(component.to_dict())
    skipped = len(items) - len(added)
    note = f" Skipped {skipped} blank or duplicate item(s)." if skipped else ""
    return _record(ctx, f"Added to '{component.title}' ({component.id}): {_fmt_items(added)}.{note}")


@function_tool
async def remove_list_items(ctx: Ctx, list_id: str, item_ids: list[str]) -> str:
    """Remove one or more items from a list in a single call.

    Args:
        list_id: Id of the list, e.g. "list-1".
        item_ids: Ids of the items to remove, e.g. ["i3", "i4"], taken from the current workspace.
    """
    try:
        component, removed, not_found = ctx.context.workspace.remove_list_items(list_id, item_ids)
    except WorkspaceError as exc:
        return f"Error: {exc}"
    await ctx.context.ui_upsert(component.to_dict())
    missing = f" Not found: {', '.join(not_found)}." if not_found else ""
    return _record(ctx, f"Removed from '{component.title}' ({component.id}): {_fmt_items(removed)}.{missing}")


@function_tool
async def delete_component(ctx: Ctx, component_id: str) -> str:
    """Close and delete a whole window (a list or a note).

    Use this when a list is no longer wanted, or a note's task is finished.

    Args:
        component_id: Id of the window to delete, e.g. "note-1" or "list-2".
    """
    try:
        component = ctx.context.workspace.delete_component(component_id)
    except WorkspaceError as exc:
        return f"Error: {exc}"
    await ctx.context.ui_delete(component.id)
    return _record(ctx, f"Deleted {component.type} '{component.title}' ({component.id}).")


@function_tool
async def say(ctx: Ctx, message: str) -> str:
    """Speak to the user. This is the only way the user hears from you.

    Args:
        message: One short, plain, factual message, e.g.
            "Added pears to the Shopping List." No personality: the voice layer adds that.
    """
    c = ctx.context
    async with c.say_lock:  # keep replies in order if calls run in parallel
        try:
            line = await pirate_line(c.voice_agent, c.user_message, message, c.spoken_this_turn)
        except Exception as exc:  # voice failed: still tell the user, plainly
            await c.activity("error", "Voice layer failed, sending plain text", repr(exc))
            line = message
        c.spoken_this_turn.append(line)
        await c.emit({"type": "say", "text": line, "plain": message})
    return "Delivered to the user."


ALL_TOOLS = [
    create_list, create_note, update_note, add_list_items,
    remove_list_items, delete_component, say,
]
