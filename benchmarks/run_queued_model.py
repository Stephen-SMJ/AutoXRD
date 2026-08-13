#!/usr/bin/env python3
"""Wait for a system unit, then run one configured model with resumable records."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("benchmarks/model_matrix.local.json"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--wait-system-unit")
    parser.add_argument("--wait-state", type=Path,
                        help="require this JSON state to say complete after the unit exits")
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    config = json.loads(args.config.read_text(encoding="utf-8"))
    matches = [item for item in config["models"] if item["model"] == args.model]
    if len(matches) != 1:
        parser.error(f"expected exactly one config entry for {args.model}")
    model = matches[0]
    state = {
        "model": args.model,
        "status": "queued" if args.wait_system_unit else "starting",
        "queued_at_utc": utc_now(),
        "wait_system_unit": args.wait_system_unit,
        "wait_state": str(args.wait_state.resolve()) if args.wait_state else None,
        "pid": os.getpid(),
        "output": str(args.output.resolve()),
    }
    atomic_json(args.state, state)

    while args.wait_system_unit:
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", args.wait_system_unit],
            check=False,
        ).returncode == 0
        if not active:
            break
        time.sleep(args.poll_seconds)

    if args.wait_state:
        try:
            prerequisite = json.loads(args.wait_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            state.update({"status": "blocked", "reason": f"prerequisite state unreadable: {exc}"})
            atomic_json(args.state, state)
            raise SystemExit(2)
        if prerequisite.get("status") != "complete":
            state.update({
                "status": "blocked",
                "reason": f"prerequisite ended with state {prerequisite.get('status')!r}",
            })
            atomic_json(args.state, state)
            raise SystemExit(2)

    state.update({"status": "running", "started_at_utc": utc_now()})
    atomic_json(args.state, state)
    command = [
        str(project / ".venv/bin/python"), "-u",
        str(project / "benchmarks/run_agent_benchmark.py"),
        "--output", str(args.output.resolve()),
        "--base-url", model["base_url"],
        "--model", model["model"],
        "--effort", model.get("effort", "high"),
        "--max-tokens", str(model.get("max_tokens", config.get("max_tokens", 8192))),
        "--tool-call-budget", str(config.get("tool_call_budget", 20)),
        "--workers", "1",
    ]
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = model["api_key"]
    result = subprocess.run(command, cwd=project, env=env)
    state.update({
        "status": "complete" if result.returncode == 0 else "command_failed",
        "finished_at_utc": utc_now(),
        "return_code": result.returncode,
    })
    atomic_json(args.state, state)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
