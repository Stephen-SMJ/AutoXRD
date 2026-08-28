from __future__ import annotations
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Iterator
from .config import DEFAULT_MODEL, default_max_tokens_for_model, resolve_model
from .llm import LLMClient
from .tool import Tool, ToolResult
from .permissions import PermissionChecker

if TYPE_CHECKING:
    from features.cost_tracker import CostTracker
    from .session import SessionStore

_MAX_RETRIES = 10
_BASE_DELAY = 0.5
_MAX_DELAY = 32.0
_JITTER_FACTOR = 0.25
_MAX_PROTOCOL_REJECTIONS = 3
_MALFORMED_TOOL_CALL_RE = re.compile(
    r"<tool_call\b|<function\s*=|<function_calls\b",
    re.IGNORECASE,
)


def _compute_retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with jitter, respecting Retry-After if present."""
    if retry_after is not None and retry_after > 0:
        return retry_after
    delay = min(_BASE_DELAY * (2 ** attempt), _MAX_DELAY)
    jitter = delay * random.uniform(0, _JITTER_FACTOR)
    return delay + jitter


def _parse_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After value from API error headers, if available."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


_CONTEXT_OVERFLOW_RE = re.compile(
    r"prompt is too long|max_tokens.*exceeds.*context|input.*too large",
    re.IGNORECASE,
)


def _response_model_matches(requested: str, returned: str | None) -> bool:
    """Compare provider model provenance without accepting family aliases."""

    if not returned:
        return False
    expected = requested.strip().casefold()
    actual = returned.strip().casefold()
    if actual == expected:
        return True
    # Some first-party APIs append an immutable date snapshot to the requested
    # model name.  Do not accept semantic aliases such as ``-free`` or ``-pro``.
    suffix = actual[len(expected):] if actual.startswith(expected) else ""
    return bool(re.fullmatch(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})", suffix))


def _response_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if _block_type(block) != "text":
            continue
        if isinstance(block, dict):
            parts.append(str(block.get("text") or ""))
        else:
            parts.append(str(getattr(block, "text", "") or ""))
    return "".join(parts)


class AbortedError(Exception):
    """Raised when the current turn is aborted by the user (Esc / Ctrl+C)."""


class Engine:
    def __init__(self, tools: list[Tool], system_prompt: str,
                 permission_checker: PermissionChecker,
                 provider: str = "anthropic",
                 model: str = DEFAULT_MODEL,
                 max_tokens: int | None = None,
                 api_key: str | None = None,
                 base_url: str | None = None,
                 effort: str | None = None,
                 session_store: SessionStore | None = None,
                 cost_tracker: CostTracker | None = None,
                 advisor_model: str | None = None,
                 advisor_max_uses: int | None = None,
                 max_tool_calls: int | None = None,
                 tool_budget_notices: bool = False,
                 require_response_model_match: bool = False,
                 reject_malformed_tool_calls: bool = False):
        self._provider = provider
        self._model = resolve_model(model, provider=provider)
        self._max_tokens = max_tokens or default_max_tokens_for_model(
            self._model,
            provider=provider,
        )
        self._effort = effort
        self._client = LLMClient(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
        )
        self._tools = {t.name: t for t in tools}
        self._system_prompt = system_prompt
        self._permissions = permission_checker
        self._messages: list[dict] = []
        self._aborted = False
        self._turn_start_len: int | None = None
        self._active_stream = None  # reference to current HTTP stream
        self._session_store = session_store
        self._cost_tracker = cost_tracker
        self._advisor_model = advisor_model or "claude-opus-4-6"
        self._advisor_max_uses = advisor_max_uses if advisor_max_uses is not None else 3
        self._advisor_enabled = False
        self._max_tool_calls = max_tool_calls
        self._tool_calls_used = 0
        self._tool_budget_notices = tool_budget_notices
        self._require_response_model_match = require_response_model_match
        self._reject_malformed_tool_calls = reject_malformed_tool_calls

    # -- advisor toggle --------------------------------------------------------

    def toggle_advisor(self) -> bool:
        """Toggle advisor on/off. Returns new state."""
        self._advisor_enabled = not self._advisor_enabled
        return self._advisor_enabled

    @property
    def advisor_enabled(self) -> bool:
        return self._advisor_enabled

    # -- message accessors (for compact / resume / commands) ----------------

    def get_messages(self) -> list[dict]:
        return list(self._messages)

    def set_messages(self, messages: list[dict]) -> None:
        self._messages = [
            {
                "role": message["role"],
                "content": message.get("content", ""),
            }
            for message in messages
        ]

    def set_session_store(self, store: SessionStore | None) -> None:
        self._session_store = store

    def set_tools(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def get_model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = resolve_model(model, provider=self._provider)
        self._max_tokens = default_max_tokens_for_model(
            self._model,
            provider=self._provider,
        )

    def _persist(self, message: dict) -> None:
        """Append message to session store if available."""
        if self._session_store is not None:
            try:
                self._session_store.append_message(message)
            except Exception:
                pass  # don't break the conversation on I/O errors

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

    def last_assistant_text(self) -> str:
        """Extract text from the last assistant message."""
        if not self._messages:
            return ""
        last = self._messages[-1]
        if last.get("role") != "assistant":
            return ""
        content = last.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "".join(parts)
        return ""

    def abort(self):
        """Abort the current turn immediately.

        Matches claude-code-main's AbortController.abort(): sets flag and
        closes the active HTTP stream so the generator unblocks at once.
        """
        self._aborted = True
        if self._active_stream is not None:
            try:
                self._active_stream.close()
            except Exception:
                pass

    def cancel_turn(self):
        """Roll back messages to the state before the current turn started.

        Uses _turn_start_len (set at the beginning of submit()) to restore
        messages to the exact state before the turn. This is more robust than
        trying to walk back individual messages, especially when a turn has
        multiple tool_use/tool_result cycles.
        """
        if self._turn_start_len is not None:
            del self._messages[self._turn_start_len:]
            self._turn_start_len = None

    def submit(self, user_input: str | list) -> Iterator[tuple]:
        """Send user message; yield events until the conversation turn completes.

        Yields:
          ("text", str)                         — streamed text chunk
          ("tool_call", name, input, activity)  — before each tool executes
          ("tool_executing", name, input, activity) — after permission granted, tool running
          ("tool_result", name, input, result)  — after each tool executes
          ("waiting",)                          — text done, waiting for tool_use
          ("error", str)                        — non-fatal API error shown to user

        Raises:
          AbortedError — if abort() was called (by Esc listener or Ctrl+C)
        """
        self._aborted = False
        self._tool_calls_used = 0
        self._turn_start_len = len(self._messages)
        self._messages.append({
            "role": "user",
            "content": user_input,
        })
        self._persist(self._messages[-1])

        try:
            while True:
                if self._aborted:
                    raise AbortedError()

                tool_uses = []

                # API call with retry
                final = None
                protocol_rejections = 0
                for attempt in range(_MAX_RETRIES):
                    try:
                        _api_t0 = time.monotonic()
                        budget_available = (
                            self._max_tool_calls is None
                            or self._tool_calls_used < self._max_tool_calls
                        )
                        tools = ([t.to_api_schema() for t in self._tools.values()]
                                 if budget_available else [])
                        if self._advisor_enabled:
                            tools.append({
                                "type": "advisor_20260301",
                                "name": "advisor",
                                "model": self._advisor_model,
                                "max_uses": self._advisor_max_uses,
                            })
                        stream_obj = self._client.stream_messages(
                            model=self._model,
                            max_tokens=self._max_tokens,
                            system=self._system_prompt,
                            tools=tools,
                            messages=self._messages,
                            effort=self._effort,
                        )
                        self._active_stream = stream_obj
                        with stream_obj as stream:
                            got_text = False
                            buffered_text: list[str] = []
                            for text in stream.text_stream:
                                if self._aborted:
                                    raise AbortedError()
                                got_text = True
                                if (self._require_response_model_match
                                        or self._reject_malformed_tool_calls):
                                    buffered_text.append(text)
                                else:
                                    yield ("text", text)

                            if self._aborted:
                                raise AbortedError()

                            final = stream.get_final_message()
                            _api_elapsed = time.monotonic() - _api_t0
                            response_tool_uses = [
                                block for block in final.content
                                if _block_type(block) == "tool_use"
                            ]
                            rejection_type = None
                            rejection_message = None
                            if (self._require_response_model_match
                                    and not _response_model_matches(
                                        self._model, final.response_model,
                                    )):
                                rejection_type = "ResponseModelMismatch"
                                rejection_message = (
                                    f"requested {self._model!r}, provider returned "
                                    f"{final.response_model!r}"
                                )
                            elif (self._reject_malformed_tool_calls
                                  and not response_tool_uses
                                  and _MALFORMED_TOOL_CALL_RE.search(
                                      _response_text(final.content)[:4096]
                                  )):
                                rejection_type = "MalformedToolCall"
                                rejection_message = (
                                    "provider returned tool-call markup as plain text"
                                )

                            attempt_status = "rejected" if rejection_type else "ok"
                            yield ("api_attempt", {
                                "attempt": attempt + 1,
                                "status": attempt_status,
                                "duration_seconds": _api_elapsed,
                                "stop_reason": final.stop_reason,
                                "requested_model": self._model,
                                "response_model": final.response_model,
                                **({
                                    "error_type": rejection_type,
                                    "message": rejection_message,
                                } if rejection_type else {}),
                            })
                            # Track token usage / cost
                            if final.usage and self._cost_tracker:
                                self._cost_tracker.add_usage(self._model, {
                                    "input_tokens": getattr(final.usage, "input_tokens", 0) or 0,
                                    "output_tokens": getattr(final.usage, "output_tokens", 0) or 0,
                                    "cache_read_input_tokens": getattr(final.usage, "cache_read_input_tokens", 0) or 0,
                                    "cache_creation_input_tokens": getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
                                    "advisor_input_tokens": getattr(final.usage, "advisor_input_tokens", 0) or 0,
                                    "advisor_output_tokens": getattr(final.usage, "advisor_output_tokens", 0) or 0,
                                }, api_duration_s=_api_elapsed, advisor_model=self._advisor_model if self._advisor_enabled else None)
                                yield ("usage", final.usage, _api_elapsed, final.stop_reason)
                            if rejection_type:
                                protocol_rejections += 1
                                final = None
                                if protocol_rejections >= _MAX_PROTOCOL_REJECTIONS:
                                    self._messages.pop()
                                    yield (
                                        "error",
                                        f"API response rejected after {protocol_rejections} "
                                        f"protocol attempts: {rejection_message}",
                                    )
                                    return
                                yield (
                                    "error",
                                    f"API response rejected; retrying "
                                    f"({protocol_rejections}/{_MAX_PROTOCOL_REJECTIONS}): "
                                    f"{rejection_message}",
                                )
                                continue

                            if buffered_text:
                                for text in buffered_text:
                                    yield ("text", text)
                            if got_text:
                                yield ("waiting",)
                            # Warn if response was truncated by max_tokens
                            if final.stop_reason == "max_tokens":
                                yield ("error", "Response truncated: hit max_tokens limit.")
                            tool_uses.extend(response_tool_uses)
                        break  # success, exit retry loop
                    except AbortedError:
                        raise
                    except Exception as e:
                        _api_elapsed = time.monotonic() - _api_t0
                        yield ("api_attempt", {
                            "attempt": attempt + 1,
                            "status": "error",
                            "duration_seconds": _api_elapsed,
                            "error_type": type(e).__name__,
                            "message": self._client.error_message(e),
                        })
                        if self._client.is_authentication_error(e):
                            self._messages.pop()
                            yield ("error", f"Authentication failed: {self._client.error_message(e)}")
                            return
                        # Context overflow: reduce max_tokens and retry
                        err_msg = self._client.error_message(e)
                        if self._client.is_api_error(e) and _CONTEXT_OVERFLOW_RE.search(err_msg):
                            reduced = self._max_tokens // 2
                            if reduced >= 1024:
                                self._max_tokens = reduced
                                yield ("error", f"Context overflow, reducing max_tokens to {reduced} and retrying...")
                                continue
                            else:
                                self._messages.pop()
                                yield ("error", f"Context overflow and cannot reduce further: {err_msg}")
                                return
                        if self._client.is_retryable_error(e):
                            if attempt < _MAX_RETRIES - 1:
                                retry_after = _parse_retry_after(e)
                                wait = _compute_retry_delay(attempt, retry_after)
                                yield ("error", f"API error, retrying in {wait:.1f}s... ({err_msg})")
                                time.sleep(wait)
                            else:
                                self._messages.pop()
                                yield ("error", f"API error after {_MAX_RETRIES} retries: {err_msg}")
                                return
                            continue
                        if self._client.is_api_error(e):
                            self._messages.pop()
                            yield ("error", f"API error: {err_msg}")
                            return
                        if self._aborted:
                            raise AbortedError()
                        raise
                    finally:
                        self._active_stream = None

                if final is None:
                    self._messages.pop()
                    return

                self._messages.append({
                    "role": "assistant",
                    "content": final.content,
                })
                self._persist(self._messages[-1])

                if not tool_uses:
                    break

                tool_results = []

                # Partition into batches: consecutive read-only tools run in
                # parallel; a non-read-only tool runs alone.
                batches: list[list] = []
                for tu in tool_uses:
                    t = self._tools.get(_block_name(tu))
                    is_concurrent = t is not None and t.is_read_only()
                    if batches and batches[-1][0] == is_concurrent and is_concurrent:
                        batches[-1][1].append(tu)
                    else:
                        batches.append((is_concurrent, [tu]))

                for is_concurrent, batch in batches:
                    if self._aborted:
                        raise AbortedError()

                    if is_concurrent and len(batch) > 1:
                        # --- parallel execution for read-only tools ---
                        # Phase 1: emit tool_call events + check permissions
                        approved: list[tuple] = []  # (tool_use, tool, activity)
                        denied_results: dict[str, ToolResult] = {}  # by tool_use_id
                        for tu in batch:
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            tool = self._tools.get(tn)
                            act = tool.get_activity_description(**ti) if tool else None
                            yield ("tool_call", tn, ti, act)
                            if (self._max_tool_calls is not None
                                    and self._tool_calls_used >= self._max_tool_calls):
                                denied_results[_block_id(tu)] = ToolResult(
                                    content="Tool-call budget exhausted. Return the best final answer now.",
                                    is_error=True,
                                )
                            elif tool and self._permissions.check(tool, ti) == "deny":
                                denied_results[_block_id(tu)] = ToolResult(
                                    content="Permission denied.", is_error=True)
                            else:
                                self._tool_calls_used += 1
                                approved.append((tu, tool, act))

                        # Phase 2: emit tool_executing for approved, then run in parallel
                        executed_results: dict[str, ToolResult] = {}
                        if approved:
                            for tu, tool, act in approved:
                                tn = _block_name(tu)
                                ti = _block_input(tu)
                                yield ("tool_executing", tn, ti, act)

                            with ThreadPoolExecutor(max_workers=min(len(approved), 10)) as pool:
                                futures = {}
                                for tu, tool, act in approved:
                                    f = pool.submit(self._execute_tool, tu, skip_permission=True)
                                    futures[f] = tu
                                for f in as_completed(futures):
                                    tu = futures[f]
                                    try:
                                        executed_results[_block_id(tu)] = f.result()
                                    except Exception as exc:
                                        executed_results[_block_id(tu)] = ToolResult(
                                            content=f"Tool execution error: {exc}", is_error=True)

                        # Phase 3: emit results in original batch order
                        for tu in batch:
                            tid = _block_id(tu)
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            result = denied_results.get(tid) or executed_results.get(tid)
                            if result is None:
                                result = ToolResult(content="No result", is_error=True)
                            yield ("tool_result", tn, ti, result)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": result.content,
                                "is_error": result.is_error,
                            })
                    else:
                        # --- sequential execution (single tool or non-read-only) ---
                        for tu in batch:
                            if self._aborted:
                                raise AbortedError()
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            tool = self._tools.get(tn)
                            act = tool.get_activity_description(**ti) if tool else None
                            yield ("tool_call", tn, ti, act)

                            if (self._max_tool_calls is not None
                                    and self._tool_calls_used >= self._max_tool_calls):
                                result = ToolResult(
                                    content="Tool-call budget exhausted. Return the best final answer now.",
                                    is_error=True,
                                )
                            elif tool and self._permissions.check(tool, ti) == "deny":
                                result = ToolResult(content="Permission denied.", is_error=True)
                            else:
                                self._tool_calls_used += 1
                                yield ("tool_executing", tn, ti, act)
                                result = self._execute_tool(tu, skip_permission=True)

                            yield ("tool_result", tn, ti, result)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": _block_id(tu),
                                "content": result.content,
                                "is_error": result.is_error,
                            })

                self._messages.append({
                    "role": "user",
                    "content": self._add_tool_budget_notice(tool_results),
                })
                self._persist(self._messages[-1])
        except AbortedError:
            self.cancel_turn()
            raise

    def _add_tool_budget_notice(self, tool_results: list[dict]) -> list[dict]:
        """Attach an optional progress reminder to the last tool result.

        Keeping the reminder inside a tool-result block preserves valid
        OpenAI/Anthropic tool-call ordering while making the live budget
        visible to the next model turn.
        """

        if not self._tool_budget_notices or self._max_tool_calls is None or not tool_results:
            return tool_results
        remaining = max(0, self._max_tool_calls - self._tool_calls_used)
        notice = (
            f"[AutoXRD tool-step progress: {self._tool_calls_used}/"
            f"{self._max_tool_calls} completed; {remaining} remain.]"
        )
        if 1 < remaining <= 5:
            notice += (
                f" CRITICAL: use at most the next {remaining - 1} tool steps to create "
                "ALL required deliverables, including final_report.md, and reserve the "
                "last tool step to verify that every required path exists. Stop optional analysis."
            )
        elif remaining == 1:
            notice += (
                " CRITICAL: this is the final available tool step. Use it immediately to "
                "create any missing required deliverables; do not perform optional analysis."
            )
        elif remaining == 0:
            notice += " Tool budget exhausted; return the best concise final response now."
        last = tool_results[-1]
        last["content"] = f"{last.get('content', '')}\n\n{notice}"
        return tool_results

    def _execute_tool(self, tool_use, skip_permission: bool = False) -> ToolResult:
        tool_name = _block_name(tool_use)
        tool_input = _block_input(tool_use)
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)

        if not skip_permission and self._permissions.check(tool, tool_input) == "deny":
            return ToolResult(content="Permission denied.", is_error=True)

        try:
            # Snapshot file for diff if it's a write tool we want to track
            old_lines: list[str] | None = None
            if self._cost_tracker and tool_name in ("Edit", "Write"):
                fp = tool_input.get("file_path", "")
                try:
                    from pathlib import Path
                    p = Path(fp)
                    old_lines = p.read_text().splitlines() if p.exists() else []
                except Exception:
                    old_lines = None

            result = tool.execute(**tool_input)

            # Track line changes for Edit/Write
            if self._cost_tracker and old_lines is not None and not result.is_error:
                fp = tool_input.get("file_path", "")
                try:
                    from pathlib import Path
                    new_lines = Path(fp).read_text().splitlines()
                    added = max(len(new_lines) - len(old_lines), 0)
                    removed = max(len(old_lines) - len(new_lines), 0)
                    self._cost_tracker.add_lines_changed(added, removed)
                except Exception:
                    pass

            return result
        except Exception as e:
            return ToolResult(content=f"Tool error: {e}", is_error=True)


def _block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _block_name(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("name", ""))
    return str(getattr(block, "name", ""))


def _block_id(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("id", ""))
    return str(getattr(block, "id", ""))


def _block_input(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        value = block.get("input", {})
    else:
        value = getattr(block, "input", {})
    return value if isinstance(value, dict) else {}
