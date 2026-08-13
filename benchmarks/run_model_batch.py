#!/usr/bin/env python3
"""Run a resumable multi-model AutoXRD benchmark batch."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_model(model: str) -> str:
    return "".join(character if character.isalnum() or character in ".-_" else "-"
                   for character in model)


def record_counts(output: Path) -> dict[str, int]:
    statuses: Counter[str] = Counter()
    for path in (output / "records").glob("*.json"):
        try:
            statuses[json.loads(path.read_text(encoding="utf-8"))["status"]] += 1
        except (OSError, json.JSONDecodeError, KeyError):
            statuses["unreadable"] += 1
    statuses["total"] = sum(value for key, value in statuses.items() if key != "unreadable")
    return dict(statuses)


def public_model_config(model: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in model.items() if key != "api_key"}


def probe(project: Path, model: dict[str, Any], timeout: int) -> dict[str, Any]:
    command = [
        str(project / ".venv/bin/python"),
        str(project / "benchmarks/probe_openai_model.py"),
        "--base-url", model["base_url"],
        "--model", model["model"],
        "--effort", model.get("effort", "high"),
    ]
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = model["api_key"]
    started = utc_now()
    try:
        result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True,
                                timeout=timeout)
        detail = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
        return {
            "ok": result.returncode == 0 and bool(detail.get("ok")),
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "return_code": result.returncode,
            "detail": detail,
            "error": result.stderr.strip()[-2000:] if result.returncode else "",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "started_at_utc": started, "finished_at_utc": utc_now(),
                "error": f"probe timed out after {timeout}s"}
    except (OSError, json.JSONDecodeError, IndexError) as exc:
        return {"ok": False, "started_at_utc": started, "finished_at_utc": utc_now(),
                "error": f"{type(exc).__name__}: {exc}"}


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config.get("models"), list) or not config["models"]:
        raise ValueError("config.models must be a non-empty list")
    required = {"model", "base_url", "api_key"}
    for index, model in enumerate(config["models"]):
        missing = required - model.keys()
        if missing:
            raise ValueError(f"models[{index}] missing: {', '.join(sorted(missing))}")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("benchmarks/model_matrix.local.json"))
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--skip-probe", action="store_true")
    parser.add_argument("--recovery", action="store_true",
                        help="make one additional attempt only for missing/error records")
    parser.add_argument("--models", nargs="*", help="optional exact model-name subset")
    parser.add_argument("--model-workers", type=int,
                        help="models to run concurrently; each model still uses one case worker")
    parser.add_argument("--probe-timeout", type=int, default=120)
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    config = load_config(args.config.resolve())
    output_root = (args.output_root or Path(config["output_root"])).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    models = [model for model in config["models"]
              if not args.models or model["model"] in args.models]
    model_workers = args.model_workers or int(config.get("model_workers", 1))
    if model_workers < 1:
        parser.error("--model-workers must be at least 1")
    model_workers = min(model_workers, len(models))
    manifest = {
        "batch_id": config.get("batch_id", output_root.name),
        "benchmark": config.get("benchmark", "autoxrd-bench-100-v2"),
        "models": [public_model_config(model) for model in models],
        "existing_runs": config.get("existing_runs", []),
        "protocol": {
            "solver_workers_per_model": 1,
            "model_workers": model_workers,
            "models_run_concurrently": model_workers > 1,
            "tool_call_budget": config.get("tool_call_budget", 20),
            "max_tokens": config.get("max_tokens", 8192),
            "initial_errors_preserved": True,
            "recovery_attempts_per_invocation": 1,
            "judge_deferred": True,
        },
    }
    atomic_json(output_root / "manifest.json", manifest)

    state_path = output_root / ("recovery-state.json" if args.recovery else "batch-state.json")
    state: dict[str, Any] = {
        "batch_id": manifest["batch_id"],
        "phase": "recovery" if args.recovery else ("probe" if args.probe_only else "initial"),
        "status": "running",
        "pid": os.getpid(),
        "started_at_utc": utc_now(),
        "models": {},
    }
    atomic_json(state_path, state)

    probe_results: dict[str, Any] = {}
    if not args.skip_probe:
        for model in models:
            name = model["model"]
            print(json.dumps({"event": "probe_started", "model": name}), flush=True)
            probe_results[name] = probe(project, model, args.probe_timeout)
            atomic_json(output_root / "probes.json", probe_results)
            print(json.dumps({"event": "probe_finished", "model": name,
                              "ok": probe_results[name]["ok"]}), flush=True)
        if args.probe_only:
            state["status"] = "complete"
            state["finished_at_utc"] = utc_now()
            state["probe_results"] = probe_results
            atomic_json(state_path, state)
            return

    state_lock = Lock()

    def write_state() -> None:
        with state_lock:
            atomic_json(state_path, state)

    def run_model(model: dict[str, Any]) -> tuple[str, int, dict[str, int]]:
        name = model["model"]
        output = output_root / safe_model(name)
        log_path = output_root / "logs" / f"{safe_model(name)}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if probe_results and not probe_results[name]["ok"]:
            with state_lock:
                state["models"][name] = {
                    "status": "probe_failed", "probe": probe_results[name]
                }
                atomic_json(state_path, state)
            return name, 2, record_counts(output)

        command = [
            str(project / ".venv/bin/python"), "-u",
            str(project / "benchmarks/run_agent_benchmark.py"),
            "--output", str(output),
            "--base-url", model["base_url"],
            "--model", name,
            "--effort", model.get("effort", "high"),
            "--max-tokens", str(model.get("max_tokens", config.get("max_tokens", 8192))),
            "--tool-call-budget", str(config.get("tool_call_budget", 20)),
            "--workers", "1",
        ]
        if args.recovery:
            command.append("--retry-errors-only")
        env = dict(os.environ)
        env["OPENAI_API_KEY"] = model["api_key"]
        with state_lock:
            state["models"][name] = {
                "status": "running", "started_at_utc": utc_now(),
                "output": str(output), "log": str(log_path), "records": record_counts(output),
            }
            state["active_models"] = sorted(
                model_name for model_name, detail in state["models"].items()
                if detail["status"] == "running"
            )
            atomic_json(state_path, state)
        print(json.dumps({"event": "model_started", "model": name, "log": str(log_path)}),
              flush=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"event": "invocation_started", "at": utc_now(),
                                  "phase": state["phase"]}) + "\n")
            log.flush()
            result = subprocess.run(command, cwd=project, env=env, stdout=log,
                                    stderr=subprocess.STDOUT)
        counts = record_counts(output)
        with state_lock:
            state["models"][name].update({
                "status": "complete" if result.returncode == 0 else "command_failed",
                "finished_at_utc": utc_now(), "return_code": result.returncode,
                "records": counts,
            })
            state["active_models"] = sorted(
                model_name for model_name, detail in state["models"].items()
                if detail["status"] == "running"
            )
            atomic_json(state_path, state)
        print(json.dumps({"event": "model_finished", "model": name,
                          "return_code": result.returncode, "records": counts}), flush=True)
        return name, result.returncode, counts

    with ThreadPoolExecutor(max_workers=model_workers) as executor:
        futures = [executor.submit(run_model, model) for model in models]
        for future in as_completed(futures):
            future.result()

    state.pop("current_model", None)
    state["active_models"] = []
    state["status"] = "complete"
    state["finished_at_utc"] = utc_now()
    atomic_json(state_path, state)


if __name__ == "__main__":
    main()
