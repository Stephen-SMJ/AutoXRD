"""Todo list for tracking plan execution progress.

Provides a simple task list the agent can create/update during multi-step
work.  The TUI renders it as a live checklist with status icons.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TodoItem:
    id: str
    subject: str
    status: str = "pending"  # "pending" | "in_progress" | "completed"

    _VALID_STATUSES = frozenset({"pending", "in_progress", "completed"})


class TodoManager:
    """Holds the current todo list state.  Shared between tools and TUI."""

    def __init__(self) -> None:
        self._items: dict[str, TodoItem] = {}
        self._next_id: int = 1

    # -- mutations ------------------------------------------------------------

    def create(self, subject: str, status: str = "pending") -> TodoItem:
        item = TodoItem(id=str(self._next_id), subject=subject, status=status)
        self._items[item.id] = item
        self._next_id += 1
        return item

    def update(
        self,
        item_id: str,
        status: str | None = None,
        subject: str | None = None,
    ) -> TodoItem | None:
        item = self._items.get(item_id)
        if item is None:
            return None
        if status is not None and status in TodoItem._VALID_STATUSES:
            item.status = status
        if subject is not None:
            item.subject = subject
        return item

    def clear(self) -> None:
        self._items.clear()
        self._next_id = 1

    # -- queries --------------------------------------------------------------

    def get(self, item_id: str) -> TodoItem | None:
        return self._items.get(item_id)

    def get_items(self) -> list[TodoItem]:
        return list(self._items.values())

    def in_progress_item(self) -> TodoItem | None:
        """Return the first in-progress item, if any."""
        for item in self._items.values():
            if item.status == "in_progress":
                return item
        return None
