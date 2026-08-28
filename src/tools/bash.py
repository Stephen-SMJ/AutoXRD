from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from core.tool import Tool, ToolResult

if TYPE_CHECKING:
    from features.sandbox.manager import SandboxManager

_DEFAULT_TIMEOUT = 120
_CD_RE = re.compile(r"(?:^|&&|;|\n)\s*cd\s+(?P<path>(?:'[^']*'|\"[^\"]*\"|[^\s;&]+))")
_OUTPUT_LIMIT = 10_000


class BashTool(Tool):
    name = "Bash"
    description = (
        "Executes a command with Bash errexit and pipefail enabled, and returns its output.\n\n"
        "The working directory persists between commands, but shell state does not. "
        "The shell does not load the user's interactive profile.\n\n"
        "IMPORTANT: Avoid using this tool to run `find`, `grep`, `cat`, `head`, `tail`, "
        "`sed`, `awk`, or `echo` commands, unless explicitly instructed or after you have "
        "verified that a dedicated tool cannot accomplish your task. Instead, use the appropriate "
        "dedicated tool as this will provide a much better experience for the user:\n\n"
        " - File search: Use Glob (NOT find or ls)\n"
        " - Content search: Use Grep (NOT grep or rg)\n"
        " - Read files: Use Read (NOT cat/head/tail)\n"
        " - Edit files: Use Edit (NOT sed/awk)\n"
        " - Write files: Use Write (NOT echo >/cat <<EOF)\n"
        " - Communication: Output text directly (NOT echo/printf)\n"
        "While the Bash tool can do similar things, it's better to use the built-in tools "
        "as they provide a better user experience and make it easier to review tool calls and give permission.\n\n"
        "# Instructions\n"
        " - If your command will create new directories or files, first use this tool to run `ls` "
        "to verify the parent directory exists and is the correct location.\n"
        " - Always quote file paths that contain spaces with double quotes in your command.\n"
        " - Try to maintain your current working directory throughout the session by using absolute paths "
        "and avoiding usage of `cd`. You may use `cd` if the User explicitly requests it.\n"
        " - You may specify an optional timeout in seconds (default 120s).\n"
        " - When issuing multiple commands:\n"
        "   - If the commands are independent and can run in parallel, make multiple Bash tool calls in a single message.\n"
        "   - If the commands depend on each other and must run sequentially, use a single Bash call with '&&' to chain them together.\n"
        "   - Use ';' only when you need to run commands sequentially but don't care if earlier commands fail.\n"
        "   - DO NOT use newlines to separate commands (newlines are ok in quoted strings).\n"
        " - For git commands:\n"
        "   - Prefer to create a new commit rather than amending an existing commit.\n"
        "   - Before running destructive operations (e.g., git reset --hard, git push --force, git checkout --), "
        "consider whether there is a safer alternative that achieves the same goal.\n"
        "   - Never skip hooks (--no-verify) or bypass signing unless the user has explicitly asked for it. "
        "If a hook fails, investigate and fix the underlying issue.\n"
        " - Avoid unnecessary `sleep` commands:\n"
        "   - Do not sleep between commands that can run immediately \u2014 just run them.\n"
        "   - Do not retry failing commands in a sleep loop \u2014 diagnose the root cause.\n"
        "   - If you must sleep, keep the duration short (1-5 seconds) to avoid blocking the user."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command to execute"},
            "description": {
                "type": "string",
                "description": "Clear, concise description of what this command does in active voice",
            },
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
            "dangerously_disable_sandbox": {
                "type": "boolean",
                "description": "If true and allowed by config, run outside sandbox",
            },
        },
        "required": ["command"],
    }

    def get_activity_description(self, **kwargs) -> str | None:
        command = kwargs.get("command", "")
        # Show a truncated version of the command
        preview = command[:60] + "…" if len(command) > 60 else command
        return f"Running {preview}" if command else None

    def __init__(self, sandbox_manager: SandboxManager | None = None,
                 cwd: str | Path | None = None):
        self._sandbox = sandbox_manager
        self._cwd = Path(cwd).resolve() if cwd is not None else None

    def execute(
        self,
        command: str,
        description: str = "",
        timeout: int = _DEFAULT_TIMEOUT,
        dangerously_disable_sandbox: bool = False,
    ) -> ToolResult:
        # Sandbox decision
        use_sandbox = (
            self._sandbox is not None
            and self._sandbox.should_sandbox(command, dangerously_disable_sandbox)
        )

        # A caller can pin a workspace without changing the user's
        # interactive shell.  SandboxManager implementations may also need the
        # working directory when constructing their wrapper command.
        if use_sandbox:
            if self._cwd is None:
                actual_command = self._sandbox.wrap(command)
            else:
                try:
                    actual_command = self._sandbox.wrap(command, str(self._cwd))
                except TypeError:
                    actual_command = self._sandbox.wrap(command)
        else:
            actual_command = command

        if not use_sandbox:
            actual_command = "set -e -o pipefail; " + actual_command

        started = time.monotonic()
        try:
            process = subprocess.Popen(
                actual_command,
                shell=True,
                executable="/bin/bash",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self._cwd) if self._cwd is not None else None,
                start_new_session=True,
            )
        except Exception as exc:
            return ToolResult(
                content=f"Error: {exc}", is_error=True,
                metadata={"returncode": None, "timed_out": False,
                          "duration_seconds": time.monotonic() - started},
            )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            returncode = process.returncode
            # The public Bash contract promises a persistent working
            # directory while shell variables/process state remain ephemeral.
            # Persist only an explicit successful `cd`; creating a directory
            # must never silently change the next command's cwd.
            if returncode == 0 and self._cwd is not None:
                last_cd = None
                for match in _CD_RE.finditer(command):
                    last_cd = match.group("path")
                if last_cd:
                    try:
                        target = Path(shlex.split(last_cd)[0])
                        if not target.is_absolute():
                            target = self._cwd / target
                        target = target.resolve()
                        if target.is_dir():
                            self._cwd = target
                    except (ValueError, OSError):
                        pass
            parts = []
            if stdout:
                parts.append(_bounded_stream(stdout, "stdout"))
            if stderr:
                parts.append(f"[stderr]\n{_bounded_stream(stderr, 'stderr')}")
            if returncode != 0:
                parts.append(f"[exit code: {returncode}]")
            return ToolResult(
                content="\n".join(parts) if parts else "(no output)",
                is_error=returncode != 0,
                metadata={
                    "returncode": returncode,
                    "timed_out": False,
                    "duration_seconds": time.monotonic() - started,
                },
            )
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            stdout, stderr = process.communicate()
            parts = [f"Error: Command timed out after {timeout}s"]
            if stdout:
                parts.append(_bounded_stream(stdout, "stdout"))
            if stderr:
                parts.append(f"[stderr]\n{_bounded_stream(stderr, 'stderr')}")
            return ToolResult(
                content="\n".join(parts),
                is_error=True,
                metadata={
                    "returncode": 124,
                    "timed_out": True,
                    "duration_seconds": time.monotonic() - started,
                },
            )
        except Exception as e:
            _terminate_process_group(process)
            return ToolResult(
                content=f"Error: {e}",
                is_error=True,
                metadata={
                    "returncode": process.poll(),
                    "timed_out": False,
                    "duration_seconds": time.monotonic() - started,
                },
            )


def _bounded_stream(value: str, label: str) -> str:
    text = value.rstrip()
    if len(text) <= _OUTPUT_LIMIT:
        return text
    return (
        text[:_OUTPUT_LIMIT]
        + f"\n\n... ({label} truncated, full output was {len(text)} chars)"
    )


def _terminate_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
