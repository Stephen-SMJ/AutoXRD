"""Tests for the todo list feature (TodoManager, tools, rendering)."""

import pytest
from io import StringIO
from unittest.mock import MagicMock

from features.todo import TodoItem, TodoManager
from tools.todo import TodoWriteTool, TodoUpdateTool


# ---------------------------------------------------------------------------
# TodoManager
# ---------------------------------------------------------------------------

def test_manager_create_item():
    mgr = TodoManager()
    item = mgr.create("Write tests")
    assert item.id == "1"
    assert item.subject == "Write tests"
    assert item.status == "pending"


def test_manager_create_increments_id():
    mgr = TodoManager()
    a = mgr.create("First")
    b = mgr.create("Second")
    assert a.id == "1"
    assert b.id == "2"


def test_manager_create_with_status():
    mgr = TodoManager()
    item = mgr.create("Already done", status="completed")
    assert item.status == "completed"


def test_manager_update_status():
    mgr = TodoManager()
    mgr.create("Task")
    updated = mgr.update("1", status="in_progress")
    assert updated is not None
    assert updated.status == "in_progress"


def test_manager_update_subject():
    mgr = TodoManager()
    mgr.create("Old name")
    updated = mgr.update("1", subject="New name")
    assert updated.subject == "New name"


def test_manager_update_nonexistent():
    mgr = TodoManager()
    assert mgr.update("99", status="completed") is None


def test_manager_update_invalid_status_ignored():
    mgr = TodoManager()
    mgr.create("Task")
    updated = mgr.update("1", status="bogus")
    assert updated.status == "pending"  # unchanged


def test_manager_clear():
    mgr = TodoManager()
    mgr.create("A")
    mgr.create("B")
    mgr.clear()
    assert mgr.get_items() == []
    # IDs reset after clear
    item = mgr.create("C")
    assert item.id == "1"


def test_manager_get():
    mgr = TodoManager()
    mgr.create("Task")
    assert mgr.get("1") is not None
    assert mgr.get("99") is None


def test_manager_get_items_order():
    mgr = TodoManager()
    mgr.create("A")
    mgr.create("B")
    mgr.create("C")
    items = mgr.get_items()
    assert [i.subject for i in items] == ["A", "B", "C"]


def test_manager_in_progress_item():
    mgr = TodoManager()
    mgr.create("A")
    mgr.create("B")
    assert mgr.in_progress_item() is None
    mgr.update("2", status="in_progress")
    wip = mgr.in_progress_item()
    assert wip is not None
    assert wip.id == "2"


# ---------------------------------------------------------------------------
# TodoWriteTool
# ---------------------------------------------------------------------------

def test_write_tool_creates_items():
    mgr = TodoManager()
    tool = TodoWriteTool(mgr)
    result = tool.execute(todos=[
        {"subject": "Step 1"},
        {"subject": "Step 2", "status": "in_progress"},
        {"subject": "Step 3"},
    ])
    assert not result.is_error
    assert "3 todo items" in result.content
    items = mgr.get_items()
    assert len(items) == 3
    assert items[0].status == "pending"
    assert items[1].status == "in_progress"


def test_write_tool_replaces_existing():
    mgr = TodoManager()
    tool = TodoWriteTool(mgr)
    tool.execute(todos=[{"subject": "Old"}])
    tool.execute(todos=[{"subject": "New A"}, {"subject": "New B"}])
    items = mgr.get_items()
    assert len(items) == 2
    assert items[0].subject == "New A"


def test_write_tool_activity():
    mgr = TodoManager()
    tool = TodoWriteTool(mgr)
    assert tool.get_activity_description() == "Creating todo list…"


# ---------------------------------------------------------------------------
# TodoUpdateTool
# ---------------------------------------------------------------------------

def test_update_tool_changes_status():
    mgr = TodoManager()
    mgr.create("Task")
    tool = TodoUpdateTool(mgr)
    result = tool.execute(id="1", status="completed")
    assert not result.is_error
    assert "completed" in result.content
    assert mgr.get("1").status == "completed"


def test_update_tool_changes_subject():
    mgr = TodoManager()
    mgr.create("Old")
    tool = TodoUpdateTool(mgr)
    result = tool.execute(id="1", subject="New")
    assert not result.is_error
    assert mgr.get("1").subject == "New"


def test_update_tool_not_found():
    mgr = TodoManager()
    tool = TodoUpdateTool(mgr)
    result = tool.execute(id="99")
    assert result.is_error
    assert "not found" in result.content


def test_update_tool_activity_in_progress():
    mgr = TodoManager()
    mgr.create("Fix the bug")
    tool = TodoUpdateTool(mgr)
    desc = tool.get_activity_description(id="1", status="in_progress")
    assert desc == "Fix the bug"


def test_update_tool_activity_other():
    mgr = TodoManager()
    mgr.create("Task")
    tool = TodoUpdateTool(mgr)
    desc = tool.get_activity_description(id="1", status="completed")
    assert "Updating todo" in desc


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_todo_list():
    from rich.console import Console
    from tui.rendering import render_todo_list
    from features.todo import TodoItem

    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=80)

    items = [
        TodoItem(id="1", subject="Done task", status="completed"),
        TodoItem(id="2", subject="Active task", status="in_progress"),
        TodoItem(id="3", subject="Pending task", status="pending"),
    ]
    render_todo_list(items, c)
    output = buf.getvalue()
    assert "Done task" in output
    assert "Active task" in output
    assert "Pending task" in output


def test_render_todo_list_truncates_long_subject():
    from rich.console import Console
    from tui.rendering import render_todo_list
    from features.todo import TodoItem

    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=120)

    long_subject = "A" * 100
    items = [TodoItem(id="1", subject=long_subject, status="pending")]
    render_todo_list(items, c)
    output = buf.getvalue()
    assert "…" in output
    assert long_subject not in output  # should be truncated
