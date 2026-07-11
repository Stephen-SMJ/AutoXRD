---
name: citorigin
description: Run, inspect, and explain CitOrigin evidence-to-claim audit workflows.
context: inline
allowed-tools: Bash, Read, Grep, Glob
arguments: task
---

# Execute CitOrigin Task

User request:

```text
${task}
```

Execute the user request now. This is not a request to describe the skill.

Use this skill for CitOrigin run, inspect, debug, visualize, and explain workflows.

CitOrigin is an audit tool, not a generation tool. The main workflow is:

1. Input externally provided evidence blocks or source documents plus claims.
2. Choose an audit method:
   - `shapley`: exact full-subset attribution
   - `drop_hold_per_unit`: SelfCite-style diagnostics with `drop`, `hold`, and `selfcite_reward`
   - `shapley,drop_hold_per_unit`: output both
3. Generate a front-end HTML result page for inspection.

Do not answer with a generic readiness message. If the request already names a workflow, file, example id, or output path, complete that task in this turn.

## Repository Assumptions

Assume the current working directory is the CitOrigin project root.

Use the active Python environment. Prefer:

```bash
PYTHONPATH=src python -m citorigin.cli ...
```

If the project is already installed in the environment, `python -m citorigin.cli ...`
also works.

Use relative paths from the repository root. Do not assume any machine-specific absolute
paths.

## Interpret Arguments

Read `$ARGUMENTS` and choose the closest workflow:

- Payload scoring: user provides one JSON payload path or says `input-path`, `documents`, `claims`, `evidence blocks`.
- File-based scoring: user provides one claim plus PDF/TXT/JSON evidence files.
- Example-dir scoring: user points to an example directory with PDFs or `documents.json` plus a claims file.
- Visualization: user asks for HTML, front-end display, result page, or `生成可视化 html`.
- Output inspection: user asks to explain a result JSON, compare Shapley vs SelfCite-style scores, or summarize top evidence blocks.
- Project status: user asks for current scope, workflow summary, or handoff context.

If the requested workflow would overwrite an existing output file, choose a new timestamped or descriptive output path unless the user explicitly asked to overwrite.

## Main Product Workflow

When the user asks for the main CitOrigin workflow, interpret it as:

### A. Prepare input

Use one of these three inputs:

1. One payload JSON for `score-claim`
2. One claim text plus evidence files for `score-claim-from-files`
3. One example directory plus claims JSON for `score-claims-from-example`

### B. Choose audit method

- `shapley`
  - Exact full-subset attribution
  - Main output: `attribution.shapley_values`, `support_strength`, `weakly_grounded`
- `drop_hold_per_unit`
  - SelfCite-style per-evidence diagnostics
  - Main output: `drop_from_full`, `hold_vs_empty`, `selfcite_reward`
- `shapley,drop_hold_per_unit`
  - Output both exact Shapley and SelfCite-style diagnostics

If the user does not specify, default to:

```text
shapley
```

### C. Front-end display

After scoring, use:

```text
scripts/build_attribution_reader_demo.py
```

This HTML builder supports:

- single-claim result JSON from `score-claim`
- batch result JSON from `score-claims-from-example`
- metric switching when `audit_outputs.drop_hold_per_unit` is present:
  - `Shapley`
  - `SelfCite-style`
  - `Hold`
  - `Drop`

## Payload Scoring Workflow

Use this when the user provides a JSON payload or wants to score externally provided evidence blocks and claims.

Expected payload shape:

```json
{
  "question": "optional string",
  "claim_text": "required string",
  "documents": [
    {
      "doc_id": "d1",
      "title": "optional string",
      "content": "required string"
    }
  ]
}
```

Run:

```bash
PYTHONPATH=src python \
  -m citorigin.cli score-claim \
  --provider <local_or_api> \
  --audit-methods <audit_methods> \
  --input-path <payload_json_path> \
  --output-path <result_json_path>
```

If `--provider local`, include:

```text
--model-path <model_path> --generator-backend transformers --device-map auto --torch-dtype bfloat16
```

If `--provider api`, include:

```text
--api-config-path ./api_config.env
```

## File-Based Scoring Workflow

Use this when the user gives one claim text plus evidence files.

Supported evidence inputs:

- `--pdf-path`
- `--txt-path`
- `--doc-json-path`

Run:

```bash
PYTHONPATH=src python \
  -m citorigin.cli score-claim-from-files \
  --provider <local_or_api> \
  --audit-methods <audit_methods> \
  --claim-text "<claim_text>" \
  --question "<optional question>" \
  --pdf-path <pdf1> \
  --pdf-path <pdf2> \
  --doc-json-path <json1> \
  --output-path <result_json_path>
```

Use this workflow when the user talks about:

- evidence blocks
- PDF evidence
- TXT evidence
- manually prepared JSON evidence units

## Example-Dir Scoring Workflow

Use this when the user has multiple claims plus documents packaged under one folder.

Expected example directory contents:

- one or more `*.pdf`, or
- `documents.json`

Claims input:

- `claims.json`, or
- a user-specified claims JSON path

Run:

```bash
PYTHONPATH=src python \
  -m citorigin.cli score-claims-from-example \
  --provider <local_or_api> \
  --audit-methods <audit_methods> \
  --example-dir <example_dir> \
  --claims-path <claims_json_path> \
  --output-path <result_json_path>
```

This is the best workflow when the user says:

- input evidence blocks and claims
- run one batch
- score a set of claims
- generate one result file for later visualization

## Visualization Workflow

Use this whenever the user asks for:

- HTML
- front-end display
- result page
- `生成可视化 html`

Run:

```bash
python scripts/build_attribution_reader_demo.py \
  --result-path <result_json_path> \
  --claims-path <claims_json_path_if_needed> \
  --output-html <output_html_path>
```

If the result JSON is from:

- `score-claim`
  - `claims-path` is optional
- `score-claims-from-example`
  - pass the claims JSON path when available so the page shows the intended claim text

After generation, report both paths:

- result JSON
- output HTML

## Output Inspection Workflow

Use this when the user asks to explain or compare results.

If the result contains `attribution`, summarize:

- `shapley_values`
- `normalized_shapley_values`
- `support_strength`
- `weakly_grounded`
- `dominant_segments`

If the result contains `audit_outputs.drop_hold_per_unit`, summarize:

- `drop_from_full`
- `hold_vs_empty`
- `selfcite_reward`
- top-ranked evidence blocks under each metric

When comparing methods:

- do not compare API and local raw values as if they are on the same scale
- compare rank order and evidence selection patterns
- explain that `selfcite_reward = drop + hold`

## Project Status Workflow

Use this when `$ARGUMENTS` includes `project status`, `scope`, `handoff`, or `what is this project`.

Read if present and relevant:

```text
PROJECT_STATUS.md
README.md
README_EN.md
docs/project_framing_and_evaluation_cn.md
```

Summarize:

- current project scope
- main input format
- supported audit methods
- current visualization path
- known limitations
- recommended next step

## Guardrails

- Do not print, copy, or commit `api_config.env`.
- Do not say CitOrigin generates claims or retrieves literature unless the user explicitly asks about those separate scripts.
- Treat claims and evidence as externally provided inputs.
- Do not modify source code unless the user asks for implementation changes.
