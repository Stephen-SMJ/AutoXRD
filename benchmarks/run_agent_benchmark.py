#!/usr/bin/env python3
"""Run AutoXRD as a fresh tool-using agent on each AutoXRD-Bench-100 case."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.context import build_system_prompt
from core.engine import Engine
from core.permissions import PermissionChecker
from features.cost_tracker import CostTracker
from features.skills import build_skills_prompt_section, get_skill, load_skills_from_dir
from tools import BashTool, FileReadTool, GlobTool, GrepTool
from xrd.benchmark import BENCHMARK_ID, load_suite, score_predictions, validate_data


SKILLS_BY_FAMILY = {
    "action_contract": ("xrd-trajectory-gate", "fullprof-staged-refinement"),
    "trajectory_gate": ("xrd-trajectory-gate", "xrd-physical-audit"),
    "residual_diagnosis": (
        "xrd-pattern-qc", "xrd-residual-features", "xrd-residual-diagnosis",
    ),
    "iucr_qpa": ("xrd-pattern-qc", "xrd-physical-audit", "fullprof-staged-refinement"),
    "dara_phase_identification": (
        "xrd-pattern-qc", "xrd-residual-diagnosis", "xrd-physical-audit",
    ),
}


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
        target = workspace / source.name
        shutil.copyfile(source, target)
        public_case["input"]["pattern"] = target.name
    (workspace / "case.json").write_text(
        json.dumps(public_case, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return public_case


def _system_prompt(workspace: Path, case: dict[str, Any], skills_root: Path, model: str) -> str:
    load_skills_from_dir(skills_root, source="project")
    prompt = build_system_prompt(cwd=str(workspace), model=model, memory_dir=workspace / ".memory")
    listing = build_skills_prompt_section()
    if listing:
        prompt += "\n\n" + listing
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
    previous_cwd = Path.cwd()
    os.chdir(workspace)
    started = time.monotonic()
    tracker = CostTracker()
    tool_calls: list[dict[str, Any]] = []
    errors: list[str] = []
    raw_text = ""
    try:
        engine = Engine(
            tools=[FileReadTool(), GlobTool(), GrepTool(), BashTool()],
            system_prompt=_system_prompt(workspace, public_case, skills_root, payload["model"]),
            permission_checker=PermissionChecker(auto_approve=True),
            provider="openai",
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=payload["base_url"],
            model=payload["model"],
            max_tokens=payload["max_tokens"],
            effort=payload["effort"],
            cost_tracker=tracker,
        )
        user_prompt = (
            "Read case.json and solve this single benchmark case. Inspect the pattern with tools "
            "when one is provided. Return only the response-schema JSON object."
        )
        chunks: list[str] = []
        for event in engine.submit(user_prompt):
            if event[0] == "text":
                chunks.append(event[1])
            elif event[0] == "tool_call":
                tool_calls.append({"name": event[1], "input": event[2]})
            elif event[0] == "error":
                errors.append(str(event[1]))
        raw_text = "".join(chunks) or engine.last_assistant_text()
        answer = _extract_json(raw_text)
        status = "ok"
    except Exception as exc:
        answer = {}
        status = "error"
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        os.chdir(previous_cwd)
    usage = {model: asdict(value) for model, value in tracker._model_usage.items()}
    return {
        "id": case["id"],
        "family": case["family"],
        "status": status,
        "answer": answer,
        "raw_response": raw_text,
        "errors": errors,
        "tool_calls": tool_calls,
        "tool_call_count": len(tool_calls),
        "elapsed_seconds": time.monotonic() - started,
        "usage": usage,
    }


def _load_completed(records_dir: Path) -> dict[str, dict[str, Any]]:
    completed = {}
    if not records_dir.is_dir():
        return completed
    for path in records_dir.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") == "ok" and isinstance(record.get("answer"), dict):
            completed[record["id"]] = record
    return completed


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
    parser.add_argument("--rerun-errors", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required")
    validate_data(args.suite_root)
    cases, _ = load_suite(args.suite_root)
    if args.families:
        cases = [case for case in cases if case["family"] in args.families]
    if args.limit is not None:
        cases = cases[:args.limit]

    output = args.output
    records_dir = output / "records"
    workspaces_dir = output / "workspaces"
    records_dir.mkdir(parents=True, exist_ok=True)
    completed = {} if args.rerun_errors else _load_completed(records_dir)
    pending = [case for case in cases if case["id"] not in completed]
    source_root = Path(__file__).resolve().parents[1]
    payloads = [{
        "case": case,
        "suite_root": str(args.suite_root.resolve()),
        "workspace": str((workspaces_dir / case["id"]).resolve()),
        "skills_root": str((source_root / ".autoxrd" / "skills").resolve()),
        "base_url": args.base_url,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "effort": args.effort,
    } for case in pending]

    records = dict(completed)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_run_case, payload): payload["case"]["id"] for payload in payloads}
        for future in as_completed(futures):
            record = future.result()
            records[record["id"]] = record
            path = records_dir / f"{record['id']}.json"
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({
                "id": record["id"], "status": record["status"],
                "seconds": round(record["elapsed_seconds"], 2),
                "tools": record["tool_call_count"],
            }), flush=True)

    ordered = [records[case["id"]] for case in cases if case["id"] in records]
    predictions = output / "predictions.jsonl"
    predictions.write_text("".join(
        json.dumps({"id": record["id"], "answer": record["answer"]}, sort_keys=True) + "\n"
        for record in ordered
    ), encoding="utf-8")
    report = score_predictions(args.suite_root, predictions)
    report["run"] = {
        "benchmark_id": BENCHMARK_ID,
        "base_url": args.base_url,
        "model": args.model,
        "effort": args.effort,
        "max_tokens": args.max_tokens,
        "workers": args.workers,
        "selected_cases": len(cases),
        "successful_responses": sum(record["status"] == "ok" for record in ordered),
        "total_tool_calls": sum(record["tool_call_count"] for record in ordered),
        "total_elapsed_case_seconds": sum(record["elapsed_seconds"] for record in ordered),
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    concise = {key: value for key, value in report.items() if key != "per_case"}
    print(json.dumps(concise, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
