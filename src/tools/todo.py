"""TodoWrite / TodoUpdate tools — agent-driven task checklist."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.tool import Tool, ToolResult

if TYPE_CHECKING:
    from features.todo import TodoManager


class TodoWriteTool(Tool):
    """Create or replace the todo list for tracking multi-step work."""

    name = "TodoWrite"
    description = (
        "Create or replace the task checklist shown to the user. "
        "Use when starting a multi-step task to track progress. "
        "Each item has a subject (brief imperative title) and an optional "
        "initial status (pending by default)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "List of todo items to create.",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {
                            "type": "string",
                            "description": "Brief imperative title, e.g. 'Add unit tests for auth module'.",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Initial status (default: pending).",
                        },
                    },
                    "required": ["subject"],
                },
            },
        },
        "required": ["todos"],
    }

    def __init__(self, manager: TodoManager) -> None:
        self._manager = manager

    def execute(self, todos: list) -> ToolResult:
        self._manager.clear()
        for entry in todos:
            self._manager.create(
                subject=entry["subject"],
                status=entry.get("status", "pending"),
            )
        items = self._manager.get_items()
        lines = [f"  #{it.id} [{it.status}] {it.subject}" for it in items]
        return ToolResult(content=f"Created {len(items)} todo items.\n" + "\n".join(lines))

    def get_activity_description(self, **kwargs) -> str | None:
        return "Creating todo list…"


class TodoUpdateTool(Tool):
    """Update the status or subject of a todo item."""

    name = "TodoUpdate"
    description = (
        "Update a todo item's status or subject. "
        "Set status to in_progress when starting work, completed when done."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The todo item ID (e.g. '1').",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "New status for the item.",
            },
            "subject": {
                "type": "string",
                "description": "New subject text (optional).",
            },
        },
        "required": ["id"],
    }

    def __init__(self, manager: TodoManager) -> None:
        self._manager = manager

    def execute(self, id: str, status: str | None = None, subject: str | None = None) -> ToolResult:
        item = self._manager.update(id, status=status, subject=subject)
        if item is None:
            return ToolResult(content=f"Todo item #{id} not found.", is_error=True)
        return ToolResult(content=f"Updated #{item.id}: [{item.status}] {item.subject}")

    def get_activity_description(self, **kwargs) -> str | None:
        status = kwargs.get("status", "")
        item_id = kwargs.get("id", "")
        item = self._manager.get(item_id)
        if item and status == "in_progress":
            return item.subject
        return f"Updating todo #{item_id}…"
