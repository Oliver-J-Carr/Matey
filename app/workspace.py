"""The workspace: the single source of truth for what windows are on screen.

Analogy: this is the ship's logbook. The agent changes it only through tools,
and the browser simply draws whatever the logbook says.

Plain Python, no AI here, so it is easy to test on its own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

ComponentType = Literal["list", "note"]


class WorkspaceError(Exception):
    """Raised for invalid requests (unknown id, wrong component type, ...)."""


@dataclass
class Item:
    id: str
    text: str


@dataclass
class Component:
    id: str
    type: ComponentType
    title: str
    items: list[Item] = field(default_factory=list)  # used by lists
    text: str = ""  # used by notes

    def to_dict(self) -> dict:
        return asdict(self)


class Workspace:
    """In-memory store of UI components. One per browser connection."""

    def __init__(self) -> None:
        self._components: dict[str, Component] = {}
        self._counters = {"list": 0, "note": 0, "item": 0}

    # ---- ids -------------------------------------------------------------
    def _next_id(self, kind: str) -> str:
        self._counters[kind] += 1
        prefix = {"list": "list", "note": "note", "item": "i"}[kind]
        sep = "" if kind == "item" else "-"
        return f"{prefix}{sep}{self._counters[kind]}"

    # ---- queries ---------------------------------------------------------
    def get(self, component_id: str) -> Component:
        component = self._components.get(component_id)
        if component is None:
            raise WorkspaceError(f"No component with id '{component_id}'.")
        return component

    def find_list_by_title(self, title: str) -> Component | None:
        wanted = _normalise(title)
        for c in self._components.values():
            if c.type == "list" and _normalise(c.title) == wanted:
                return c
        return None

    def components(self) -> list[Component]:
        return list(self._components.values())

    # ---- commands --------------------------------------------------------
    def create_list(self, title: str, items: list[str] | None = None) -> Component:
        title = title.strip() or "List"
        if self.find_list_by_title(title):
            raise WorkspaceError(
                f"A list titled '{title}' already exists. Add to it instead."
            )
        component = Component(id=self._next_id("list"), type="list", title=title)
        self._components[component.id] = component
        if items:
            self.add_list_items(component.id, items)
        return component

    def create_note(self, text: str, title: str = "Note") -> Component:
        component = Component(
            id=self._next_id("note"),
            type="note",
            title=title.strip() or "Note",
            text=text.strip(),
        )
        self._components[component.id] = component
        return component

    def update_note(self, note_id: str, text: str | None = None, title: str | None = None) -> tuple[Component, str]:
        """Change a note in place. Returns the note and its previous text."""
        component = self.get(note_id)
        if component.type != "note":
            raise WorkspaceError(f"'{note_id}' is a {component.type}, not a note.")
        if not (text and text.strip()) and not (title and title.strip()):
            raise WorkspaceError("Nothing to update: give new text or a new title.")
        old_text = component.text
        if text and text.strip():
            component.text = text.strip()
        if title and title.strip():
            component.title = title.strip()
        return component, old_text

    def add_list_items(self, list_id: str, items: list[str]) -> tuple[Component, list[Item]]:
        component = self._require_list(list_id)
        existing = {_normalise(i.text) for i in component.items}
        added: list[Item] = []
        for text in items:
            clean = text.strip()
            if not clean or _normalise(clean) in existing:
                continue  # skip blanks and duplicates
            item = Item(id=self._next_id("item"), text=clean)
            component.items.append(item)
            existing.add(_normalise(clean))
            added.append(item)
        return component, added

    def remove_list_items(self, list_id: str, item_ids: list[str]) -> tuple[Component, list[Item], list[str]]:
        component = self._require_list(list_id)
        wanted = set(item_ids)
        removed = [i for i in component.items if i.id in wanted]
        component.items = [i for i in component.items if i.id not in wanted]
        not_found = sorted(wanted - {i.id for i in removed})
        return component, removed, not_found

    def delete_component(self, component_id: str) -> Component:
        component = self.get(component_id)
        del self._components[component_id]
        return component

    # ---- views -----------------------------------------------------------
    def snapshot_text(self) -> str:
        """Compact, model-friendly description of everything on screen."""
        if not self._components:
            return "(no windows are open)"
        lines = []
        for c in self._components.values():
            if c.type == "list":
                items = ", ".join(f"[{i.id}] {i.text}" for i in c.items) or "(empty)"
                lines.append(f'- {c.id} | list | "{c.title}" | items: {items}')
            else:
                lines.append(f'- {c.id} | note | "{c.title}" | text: {c.text}')
        return "\n".join(lines)

    # ---- helpers ---------------------------------------------------------
    def _require_list(self, list_id: str) -> Component:
        component = self.get(list_id)
        if component.type != "list":
            raise WorkspaceError(f"'{list_id}' is a {component.type}, not a list.")
        return component


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())
