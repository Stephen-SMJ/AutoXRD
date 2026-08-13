#!/usr/bin/env python3
"""Run AutoXRD in a confined workspace on each AutoXRD-Bench-100 v2 case."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.context import build_system_prompt
from core.engine import Engine
from core.permissions import PermissionChecker
from features.cost_tracker import CostTracker
from features.skills import get_skill, load_skills_from_dir
from tools import BashTool, FileReadTool, GlobTool, GrepTool
from core.tool import ToolResult
from xrd.benchmark_v2 import BENCHMARK_ID, load_suite, score_predictions, validate_data


SKILLS_BY_FAMILY = {
    "easy_action_reasoning": ("xrd-trajectory-gate", "fullprof-staged-refinement"),
    "easy_gate_reasoning": ("xrd-trajectory-gate", "xrd-physical-audit"),
    "easy_residual_reasoning": (
        "xrd-pattern-qc", "xrd-residual-features", "xrd-residual-diagnosis",
    ),
    "medium_residual_report": ("xrd-pattern-qc", "xrd-residual-features", "xrd-residual-diagnosis"),
    "medium_trajectory_report": ("xrd-trajectory-gate", "xrd-physical-audit"),
    "medium_experimental_report": ("xrd-pattern-qc", "xrd-physical-audit"),
    "hard_metric_recovery": ("xrd-pattern-qc", "xrd-residual-features", "xrd-residual-diagnosis"),
    "hard_qpa": ("xrd-pattern-qc", "xrd-physical-audit", "fullprof-staged-refinement"),
    "hard_phase_identification": (
        "xrd-pattern-qc", "xrd-residual-diagnosis", "xrd-physical-audit",
    ),
}


class ToolBudgetExceeded(RuntimeError):
    pass


TELEMETRY_SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _inside(root: Path, candidate: str | Path) -> bool:
    try:
        Path(candidate).resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class ScopedFileReadTool(FileReadTool):
    def __init__(self, root: Path):
        self.root = root.resolve()

    def execute(self, file_path: str, offset: int = 0, limit: int = 2000) -> ToolResult:
        if not _inside(self.root, file_path):
            return ToolResult(content="Error: benchmark filesystem boundary violation", is_error=True)
        return super().execute(file_path, offset, limit)


class ScopedGlobTool(GlobTool):
    def __init__(self, root: Path):
        self.root = root.resolve()

    def execute(self, pattern: str, path: str = ".") -> ToolResult:
        candidate = self.root if path == "." else Path(path)
        if not _inside(self.root, candidate):
            return ToolResult(content="Error: benchmark filesystem boundary violation", is_error=True)
        return super().execute(pattern, str(candidate))


class ScopedGrepTool(GrepTool):
    def __init__(self, root: Path):
        self.root = root.resolve()

    def execute(self, pattern: str, path: str = ".", glob: str | None = None,
                output_mode: str = "files_with_matches", **kwargs: Any) -> ToolResult:
        candidate = self.root if path == "." else Path(path)
        if not _inside(self.root, candidate):
            return ToolResult(content="Error: benchmark filesystem boundary violation", is_error=True)
        return super().execute(pattern, str(candidate), glob, output_mode, **kwargs)


class DockerBashTool(BashTool):
    """Run every command in a networkless container that can see only one case workspace."""

    def __init__(self, root: Path, image: str):
        super().__init__()
        self.root = root.resolve()
        self.image = image

    def execute(self, command: str, description: str = "", timeout: int = 120,
                dangerously_disable_sandbox: bool = False) -> ToolResult:
        del description, dangerously_disable_sandbox
        args = [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m",
            "--volume", f"{self.root}:{self.root}:rw", "--workdir", str(self.root),
            "--entrypoint", "/bin/sh", self.image, "-lc", command,
        ]
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return ToolResult(content=f"Error: command timed out after {timeout}s", is_error=True)
        except OSError as exc:
            return ToolResult(content=f"Error: container execution failed: {exc}", is_error=True)
        output = result.stdout.rstrip()
        if result.stderr:
            output += ("\n" if output else "") + "[stderr]\n" + result.stderr.rstrip()
        if result.returncode:
            output += f"\n[exit code: {result.returncode}]"
        if len(output) > 10_000:
            output = output[:10_000] + "\n... (output truncated)"
        return ToolResult(content=output or "(no output)", is_error=result.returncode != 0)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidates = [stripped]
    if "```" in stripped:
        for block in stripped.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if block.startswith("{"):
                candidates.append(block)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            for index, character in enumerate(candidate):
                if character != "{":
                    continue
                try:
                    value, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    return value
        else:
            if isinstance(value, dict):
                return value
    raise ValueError("assistant response contains no JSON object")


def _prepare_case(case: dict[str, Any], suite_root: Path, workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    public_case = json.loads(json.dumps(case))
    relative = public_case["input"].get("pattern")
    if relative:
        source = suite_root / relative
        target = workspace / f"pattern{source.suffix.lower()}"
        shutil.copyfile(source, target)
        public_case["input"]["pattern"] = target.name
    (workspace / "case.json").write_text(
        json.dumps(public_case, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return public_case


def _prepare_skills(source: Path, workspace: Path, family: str) -> Path:
    target = workspace / ".skills"
    target.mkdir(parents=True, exist_ok=True)
    for name in SKILLS_BY_FAMILY[family]:
        source_skill = source / name
        target_skill = target / name
        if source_skill.is_dir() and not target_skill.exists():
            shutil.copytree(source_skill, target_skill)
    return target


def _system_prompt(workspace: Path, case: dict[str, Any], skills_root: Path, model: str) -> str:
    load_skills_from_dir(skills_root, source="project")
    prompt = build_system_prompt(cwd=str(workspace), model=model, memory_dir=workspace / ".memory")
    prompt += (
        "\n\n# Benchmark Protocol\n"
        "You are the AutoXRD powder-diffraction agent under evaluation. Work only inside the "
        "current case directory. The evaluator oracle is unavailable. Use the provided tools and "
        "domain skills to inspect the public case and pattern. Do not fabricate a backend result. "
        "Your final response must be exactly one JSON object matching response_schema, with no "
        "Markdown or explanatory text."
    )
    for name in SKILLS_BY_FAMILY[case["family"]]:
        skill = get_skill(name)
        if skill is not None:
            prompt += f"\n\n# Active Skill: {name}\n{skill.get_prompt()}"
    return prompt


def _run_case(payload: dict[str, Any]) -> dict[str, Any]:
    case = payload["case"]
    suite_root = Path(payload["suite_root"])
    workspace = Path(payload["workspace"])
    skills_root = Path(payload["skills_root"])
    public_case = _prepare_case(case, suite_root, workspace)
    confined_skills = _prepare_skills(skills_root, workspace, case["family"])
    previous_cwd = Path.cwd()
    os.chdir(workspace)
    started = time.monotonic()
    started_at = _utc_now()
    tracker = CostTracker()
    tool_calls: list[dict[str, Any]] = []
    model_turns: list[dict[str, Any]] = []
    api_attempts: list[dict[str, Any]] = []
    errors: list[str] = []
    raw_text = ""
    tool_calls_requested = 0
    termination_reason = "completed"
    try:
        engine = Engine(
            tools=[ScopedFileReadTool(workspace), ScopedGlobTool(workspace), ScopedGrepTool(workspace),
                   DockerBashTool(workspace, payload["sandbox_image"])],
            system_prompt=_system_prompt(workspace, public_case, confined_skills, payload["model"]),
            permission_checker=PermissionChecker(auto_approve=True),
            provider="openai",
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=payload["base_url"],
            model=payload["model"],
            max_tokens=payload["max_tokens"],
            effort=payload["effort"],
            cost_tracker=tracker,
            max_tool_calls=payload["tool_call_budget"],
        )
        user_prompt = (
            "Read case.json and solve this single benchmark case. Inspect the pattern with tools "
            "when one is provided. Easy cases are select-all-that-apply, so return every supported "
            "option and no unsupported option. Medium and hard cases require metric-grounded scientific "
            "reasoning. Return only the response-schema JSON object."
        )
        chunks: list[str] = []
        for event in engine.submit(user_prompt):
            elapsed = time.monotonic() - started
            if event[0] == "text":
                chunks.append(event[1])
            elif event[0] == "tool_call":
                tool_calls_requested += 1
                if tool_calls_requested > payload["tool_call_budget"]:
                    raise ToolBudgetExceeded(
                        f"case requested more than {payload['tool_call_budget']} tool calls"
                    )
                tool_calls.append({
                    "sequence": tool_calls_requested,
                    "name": event[1],
                    "input": event[2],
                    "requested_at_seconds": elapsed,
                    "executed": False,
                })
            elif event[0] == "tool_executing":
                for call in tool_calls:
                    if (not call["executed"] and call["name"] == event[1]
                            and call["input"] == event[2]):
                        call["executed"] = True
                        call["started_at_seconds"] = elapsed
                        break
            elif event[0] == "tool_result":
                for call in tool_calls:
                    if (call["executed"] and "finished_at_seconds" not in call
                            and call["name"] == event[1] and call["input"] == event[2]):
                        call["finished_at_seconds"] = elapsed
                        call["duration_seconds"] = elapsed - call["started_at_seconds"]
                        call["is_error"] = bool(event[3].is_error)
                        call["result_chars"] = len(event[3].content)
                        break
            elif event[0] == "usage":
                turn_usage = asdict(event[1])
                if model_turns:
                    model_turns[-1].update({
                        **turn_usage,
                        "total_tokens": turn_usage["input_tokens"] + turn_usage["output_tokens"],
                        "usage_reported": True,
                    })
            elif event[0] == "api_attempt":
                api_attempts.append({
                    "sequence": len(api_attempts) + 1,
                    "finished_at_seconds": elapsed,
                    **event[1],
                })
                if event[1]["status"] == "ok":
                    model_turns.append({
                        "sequence": len(model_turns) + 1,
                        "finished_at_seconds": elapsed,
                        "api_duration_seconds": event[1]["duration_seconds"],
                        "stop_reason": event[1].get("stop_reason"),
                        "usage_reported": False,
                    })
            elif event[0] == "error":
                errors.append(str(event[1]))
        raw_text = "".join(chunks) or engine.last_assistant_text()
        answer = _extract_json(raw_text)
        status = "ok"
    except ToolBudgetExceeded as exc:
        answer = {}
        status = "failed"
        termination_reason = "tool_budget_exceeded"
        errors.append(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        answer = {}
        status = "error"
        termination_reason = (
            "invalid_response" if isinstance(exc, ValueError) else "runner_exception"
        )
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        os.chdir(previous_cwd)
    finished_at = _utc_now()
    elapsed_seconds = time.monotonic() - started
    usage = {model: asdict(value) for model, value in tracker._model_usage.items()}
    token_totals = {
        field: sum(getattr(value, field) for value in tracker._model_usage.values())
        for field in (
            "input_tokens", "output_tokens", "cache_read_input_tokens",
            "cache_creation_input_tokens", "advisor_input_tokens", "advisor_output_tokens",
        )
    }
    token_totals["total_tokens"] = token_totals["input_tokens"] + token_totals["output_tokens"]
    executed_calls = [call for call in tool_calls if call["executed"]]
    if status == "ok" and errors:
        termination_reason = "completed_with_warnings"
    return {
        "id": case["id"],
        "family": case["family"],
        "difficulty": case["difficulty"],
        "status": status,
        "termination_reason": termination_reason,
        "attempt": payload["attempt"],
        "run_phase": payload["run_phase"],
        "answer": answer,
        "raw_response": raw_text,
        "errors": errors,
        "tool_calls": tool_calls,
        "tool_call_count": len(executed_calls),
        "tool_calls_requested": tool_calls_requested,
        "tool_calls_executed": len(executed_calls),
        "tool_errors": sum(bool(call.get("is_error")) for call in executed_calls),
        "tool_duration_seconds": sum(call.get("duration_seconds", 0.0) for call in executed_calls),
        "model_turn_count": len(model_turns),
        "agent_step_count": len(model_turns) + len(executed_calls),
        "api_attempt_count": len(api_attempts),
        "api_error_attempt_count": sum(attempt["status"] == "error" for attempt in api_attempts),
        "api_retry_count": sum(attempt["attempt"] > 1 for attempt in api_attempts),
        "model_turns": model_turns,
        "api_attempts": api_attempts,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "api_duration_seconds": tracker._total_api_duration_s,
        "non_api_wall_seconds": max(0.0, elapsed_seconds - tracker._total_api_duration_s),
        "token_totals": token_totals,
        "token_reporting_complete": all(turn["usage_reported"] for turn in model_turns),
        "usage": usage,
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
    }


def _load_records(records_dir: Path) -> dict[str, dict[str, Any]]:
    records = {}
    if not records_dir.is_dir():
        return records
    for path in records_dir.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") in {"ok", "failed", "error"} and isinstance(record.get("answer"), dict):
            records[record["id"]] = record
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", type=Path, default=Path("benchmarks/autoxrd_bench_100"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.lambda.org.ai/v1")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--families", nargs="*", choices=tuple(SKILLS_BY_FAMILY))
    parser.add_argument("--difficulties", nargs="*", choices=("easy", "medium", "hard"))
    parser.add_argument("--rerun-errors", "--retry-errors-only", action="store_true",
                        help="re-run only missing cases and records whose latest status is error")
    parser.add_argument("--rerun-difficulties", nargs="*", choices=("easy", "medium", "hard"),
                        help="rerun completed records in selected tiers")
    parser.add_argument("--tool-call-budget", type=int, default=20,
                        help="maximum requested tool calls per case unless the case declares a lower budget")
    parser.add_argument("--judgments", type=Path,
                        help="optional completed Judge JSONL for final rather than provisional scoring")
    parser.add_argument("--sandbox-image", default="lambda-sandbox:preload-safe",
                        help="local Docker image used for networkless case execution")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required")
    if shutil.which("docker") is None:
        parser.error("docker is required for benchmark isolation")
    image_check = subprocess.run(["docker", "image", "inspect", args.sandbox_image],
                                 capture_output=True)
    if image_check.returncode:
        parser.error(f"sandbox image is unavailable: {args.sandbox_image}")
    validate_data(args.suite_root)
    cases, _ = load_suite(args.suite_root)
    if args.families:
        cases = [case for case in cases if case["family"] in args.families]
    if args.difficulties:
        cases = [case for case in cases if case["difficulty"] in args.difficulties]
    if args.limit is not None:
        cases = cases[:args.limit]

    output = args.output
    records_dir = output / "records"
    attempts_dir = output / "attempts"
    workspaces_dir = output / "workspaces"
    records_dir.mkdir(parents=True, exist_ok=True)
    existing = _load_records(records_dir)
    completed = dict(existing)
    if args.rerun_errors:
        completed = {case_id: record for case_id, record in completed.items()
                     if record["status"] != "error"}
    if args.rerun_difficulties:
        rerun_ids = {case["id"] for case in cases if case["difficulty"] in args.rerun_difficulties}
        completed = {case_id: record for case_id, record in completed.items()
                     if case_id not in rerun_ids}
    pending = [case for case in cases if case["id"] not in completed]
    source_root = Path(__file__).resolve().parents[1]
    payloads = [{
        "case": case,
        "suite_root": str(args.suite_root.resolve()),
        "workspace": str((workspaces_dir / case["id"]).resolve()),
        "skills_root": str((source_root / ".autoxrd" / "skills").resolve()),
        "sandbox_image": args.sandbox_image,
        "base_url": args.base_url,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "effort": args.effort,
        "tool_call_budget": min(args.tool_call_budget, case["input"].get(
            "call_budget", args.tool_call_budget)),
        "attempt": int(existing.get(case["id"], {}).get("attempt", 0)) + 1,
        "run_phase": "recovery" if args.rerun_errors else "initial",
    } for case in pending]

    records = dict(completed)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_run_case, payload): payload["case"]["id"] for payload in payloads}
        for future in as_completed(futures):
            record = future.result()
            records[record["id"]] = record
            path = records_dir / f"{record['id']}.json"
            attempt_path = (attempts_dir / record["id"]
                            / f"attempt-{record['attempt']:03d}.json")
            _atomic_json(attempt_path, record)
            _atomic_json(path, record)
            print(json.dumps({
                "id": record["id"], "status": record["status"],
                "seconds": round(record["elapsed_seconds"], 2),
                "tools": record["tool_call_count"],
                "turns": record["model_turn_count"],
                "tokens": record["token_totals"]["total_tokens"],
                "attempt": record["attempt"],
            }), flush=True)

    ordered = [records[case["id"]] for case in cases if case["id"] in records]
    predictions = output / "predictions.jsonl"
    predictions.write_text("".join(
        json.dumps({"id": record["id"], "answer": record["answer"]}, sort_keys=True) + "\n"
        for record in ordered
    ), encoding="utf-8")
    report = score_predictions(args.suite_root, predictions, args.judgments)
    statuses = Counter(record["status"] for record in ordered)
    report["run"] = {
        "benchmark_id": BENCHMARK_ID,
        "base_url": args.base_url,
        "model": args.model,
        "effort": args.effort,
        "max_tokens": args.max_tokens,
        "workers": args.workers,
        "default_tool_call_budget": args.tool_call_budget,
        "selected_cases": len(cases),
        "successful_responses": sum(record["status"] == "ok" for record in ordered),
        "status_counts": dict(statuses),
        "total_tool_calls": sum(record.get("tool_call_count", 0) for record in ordered),
        "total_model_turns": sum(record.get("model_turn_count", 0) for record in ordered),
        "total_agent_steps": sum(record.get("agent_step_count", 0) for record in ordered),
        "total_input_tokens": sum(record.get("token_totals", {}).get("input_tokens", 0)
                                  for record in ordered),
        "total_output_tokens": sum(record.get("token_totals", {}).get("output_tokens", 0)
                                   for record in ordered),
        "total_tokens": sum(record.get("token_totals", {}).get("total_tokens", 0)
                            for record in ordered),
        "total_api_duration_seconds": sum(record.get("api_duration_seconds", 0.0)
                                          for record in ordered),
        "total_elapsed_case_seconds": sum(record["elapsed_seconds"] for record in ordered),
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "step_definition": "successful model turns + executed tool calls",
    }
    _atomic_json(output / "report.json", report)
    concise = {key: value for key, value in report.items() if key != "per_case"}
    print(json.dumps(concise, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
