"""Session persistence — JSONL-based conversation storage.

Modelled after claude-code's ``src/utils/sessionStorage.ts``.
Each session is a pair of files under ``~/.config/autoxrd/sessions/{sanitized_cwd}/``:

* ``{session_id}.jsonl``  — one JSON object per message
* ``{session_id}.meta.json`` — lightweight metadata for fast listing
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SESSIONS_ROOT = Path.home() / ".config" / "autoxrd" / "sessions"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SessionMeta:
    session_id: str
    title: str
    cwd: str
    model: str
    created_at: str
    updated_at: str
    message_count: int = 0
    mode: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_cwd(cwd: str) -> str:
    """Convert an absolute path to a safe directory name.

    Mirrors claude-code's sanitisation: replace non-alnum with ``-``, strip
    leading dashes and collapse consecutive dashes.  Append a short hash to
    avoid collisions after truncation.
    """
    name = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    name = re.sub(r"-+", "-", name).strip("-")
    if len(name) > 80:
        h = hashlib.sha1(cwd.encode()).hexdigest()[:8]
        name = name[:80] + "-" + h
    return name


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_content(content: Any) -> Any:
    """Recursively convert Anthropic SDK Pydantic objects to plain dicts."""
    if content is None:
        return content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [_serialize_content(item) for item in content]
    # Anthropic SDK content blocks are Pydantic BaseModel instances
    if hasattr(content, "model_dump"):
        return content.model_dump()
    if isinstance(content, dict):
        return {k: _serialize_content(v) for k, v in content.items()}
    return content


def _serialize_message(msg: dict) -> dict:
    """Return a JSON-safe copy of a message dict."""
    out: dict[str, Any] = {}
    for key, val in msg.items():
        if key == "content":
            out[key] = _serialize_content(val)
        else:
            out[key] = val
    return out


def _extract_text(content: Any) -> str:
    """Best-effort plain text extraction from message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif hasattr(block, "text"):
                parts.append(getattr(block, "text", ""))
        return " ".join(parts)
    return str(content)


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------

class SessionStore:
    """Manages JSONL persistence for a single session."""

    def __init__(self, cwd: str, model: str,
                 session_id: str | None = None,
                 mode: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex
        self.cwd = cwd
        self.model = model
        self.mode = mode
        self._dir = _SESSIONS_ROOT / _sanitize_cwd(cwd)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self._dir / f"{self.session_id}.jsonl"
        self._meta_path = self._dir / f"{self.session_id}.meta.json"
        self._message_count = 0
        self._title: str = ""

    # -- writing -----------------------------------------------------------

    def append_message(self, message: dict) -> None:
        """Persist one message (append to JSONL)."""
        safe = _serialize_message(message)
        safe["_ts"] = _now_iso()
        with open(self._jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(safe, ensure_ascii=False) + "\n")
        self._message_count += 1

        # Auto-generate title from first user message
        if not self._title and message.get("role") == "user":
            self._title = _generate_title(message.get("content", ""))

        self._save_meta()

    def _save_meta(self) -> None:
        now = _now_iso()
        meta = SessionMeta(
            session_id=self.session_id,
            title=self._title or "(untitled)",
            cwd=self.cwd,
            model=self.model,
            created_at=getattr(self, "_created_at", now),
            updated_at=now,
            message_count=self._message_count,
            mode=self.mode,
        )
        if not hasattr(self, "_created_at"):
            self._created_at = now
        with open(self._meta_path, "w", encoding="utf-8") as fh:
            json.dump(asdict(meta), fh, ensure_ascii=False)

    # -- reading (class methods) -------------------------------------------

    @classmethod
    def load_messages(cls, session_id: str, cwd: str) -> list[dict]:
        """Read all messages for *session_id* from disk."""
        d = _SESSIONS_ROOT / _sanitize_cwd(cwd)
        path = d / f"{session_id}.jsonl"
        if not path.exists():
            return []
        messages: list[dict] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                obj.pop("_ts", None)
                messages.append(obj)
        return messages

    @classmethod
    def list_sessions(cls, cwd: str) -> list[SessionMeta]:
        """Return available sessions for *cwd*, most recent first."""
        d = _SESSIONS_ROOT / _sanitize_cwd(cwd)
        if not d.exists():
            return []
        results: list[SessionMeta] = []
        for meta_file in d.glob("*.meta.json"):
            try:
                with open(meta_file, encoding="utf-8") as fh:
                    data = json.load(fh)
                results.append(SessionMeta(**data))
            except Exception:
                continue
        results.sort(key=lambda m: m.updated_at, reverse=True)
        return results

    @classmethod
    def load_session(cls, session_id: str, cwd: str) -> tuple[SessionMeta | None, list[dict]]:
        """Load metadata + messages for *session_id*."""
        d = _SESSIONS_ROOT / _sanitize_cwd(cwd)
        meta_path = d / f"{session_id}.meta.json"
        meta = None
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as fh:
                meta = SessionMeta(**json.load(fh))
        messages = cls.load_messages(session_id, cwd)
        return meta, messages


# ---------------------------------------------------------------------------
# Title generation
# ---------------------------------------------------------------------------

def _generate_title(content: Any) -> str:
    """Create a short title from the first user message."""
    text = _extract_text(content).strip()
    if not text:
        return "(untitled)"
    # Truncate at word boundary
    if len(text) <= 80:
        return text
    truncated = text[:80]
    last_space = truncated.rfind(" ")
    if last_space > 40:
        truncated = truncated[:last_space]
    return truncated + "…"
