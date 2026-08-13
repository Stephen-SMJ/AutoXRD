# AutoXRD

AutoXRD is a terminal-based LLM agent for powder X-ray diffraction analysis and
physically auditable Rietveld refinement. It combines a Claude Code-style interactive
agent loop with typed XRD skills, deterministic validators, FullProf and GSAS-II
backends, experimental-pattern quality control, and reproducible benchmark runners.

The central design rule is:

> The LLM plans and explains. Crystallographic software performs numerical refinement.
> Validators decide whether a result is scientifically acceptable.

A low `Rwp` is therefore never sufficient on its own. AutoXRD also checks convergence,
residual morphology, parameter stability, occupancies, displacement factors, phase
fractions, covariance, chemistry, and unresolved peaks.

## Project Status

Implemented:

- Interactive terminal UI with streaming responses and tool calls
- OpenAI-compatible and Anthropic API support
- Session persistence, context compression, memory, plans, permissions, and coordinator mode
- Two-column, opXRD JSON, and Panalytical XRDML pattern readers
- Pattern QC and conservative peak detection
- FullProf process runner and output parser
- FullProf metrics: `Rp`, `Rwp`, `Rexp`, `Chi2`, Bragg R, fractions, convergence, runtime, warnings
- FullProf PCR semantic catalog, guarded early-stage codeword compiler, and direct PRF reader
- Validated Le Bail initialization and immutable parent/child FullProf execution
- Typed scientific contracts for evidence, actions, predictions, snapshots, and gate decisions
- Evidence-gated refinement transitions with stage, bounds, coupling, and physical checks
- Deterministic residual morphology and candidate-structure auditing
- Append-only, hash-chained refinement trajectories with tamper detection
- Nine XRD skills for QC, structure audit, guarded PCR compilation, Le Bail and Rietveld
  refinement, residual analysis, gating, and final audit
- FullProf, opXRD, Dara, SimXRD, and SIMPOD benchmark infrastructure

In progress:

- CIF-to-PCR synthesis and high-risk FullProf limit/restraint compilation
- Fully autonomous staged refinement policy
- Candidate phase retrieval and search-match
- Multi-hypothesis phase identification
- End-to-end trajectory policy and artifact recovery benchmark runner

See [`proposal.md`](proposal.md) for the original proposal and
[`docs/research-design.md`](docs/research-design.md) for the implemented research abstraction,
evaluation protocol, baselines, ablations, and skill-distillation plan. See
[`docs/fullprof-pcr.md`](docs/fullprof-pcr.md) for the guarded PCR workflow and JSON contract.

## Repository Layout

```text
AutoXRD/
├── .autoxrd/skills/          # Project XRD skills
├── benchmarks/               # Manifests, runners, and benchmark documentation
├── docs/                     # TUI, configuration, memory, sandbox, and skill docs
├── resources/                # FullProf and Rietveld reference PDFs
├── src/
│   ├── core/                 # Agent engine, LLM clients, config, sessions
│   ├── features/             # Skills, memory, coordinator, plans, sandbox
│   ├── tools/                # Read/write/edit/grep/bash/agent tools
│   ├── tui/                  # Interactive terminal application
│   └── xrd/                  # Schemas, gates, trajectory, residuals, structures, backends
└── tests/                    # Unit and integration tests
```

## Requirements

- Linux or macOS; the prepared backend setup is currently tested on Ubuntu 24.04 x86-64
- Python 3.11 or newer
- Git
- An OpenAI-compatible or Anthropic API key
- FullProf for FullProf-backed numerical refinement
- GSAS-II for GSAS-II-backed scripting workflows

The core TUI can run without FullProf or GSAS-II. Numerical refinement workflows require
at least one backend.

## Quick Start

### 1. Clone

```bash
git clone git@github.com:Stephen-SMJ/AutoXRD.git
cd AutoXRD
```

HTTPS also works:

```bash
git clone https://github.com/Stephen-SMJ/AutoXRD.git
cd AutoXRD
```

### 2. Create the environment

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev,xrd]"
```

The `xrd` extra installs the common scientific stack:

- NumPy, SciPy, Pandas, Matplotlib
- Gemmi, PyCifRW, pymatgen, diffpy.structure, ASE
- pyFAI and FabIO for detector images
- xrayutilities, spglib, seekpath
- pybaselines and LMFit
- scikit-learn and Optuna
- h5py, openpyxl, Pysimxrd, and supporting packages

### 3. Configure the model

AutoXRD defaults to this OpenAI-compatible endpoint configuration:

```text
provider:   openai
base_url:   https://token-plan-sgp.xiaomimimo.com/v1
model:      mimo-v2.5-pro
max_tokens: 8192
effort:     high
```

Set the key only in the environment:

```bash
export OPENAI_API_KEY="your-api-key"
```

Do not place API keys in committed files. AutoXRD loads `.env` locally, but `.env` is ignored
by Git.

To use another OpenAI-compatible gateway:

```bash
export AUTOXRD_PROVIDER=openai
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://gateway.example.com/v1"
export AUTOXRD_MODEL="your-model"
export AUTOXRD_MAX_TOKENS=8192
export AUTOXRD_EFFORT=high
```

Anthropic example:

```bash
export AUTOXRD_PROVIDER=anthropic
export ANTHROPIC_API_KEY="your-api-key"
export AUTOXRD_MODEL="claude-sonnet-4-6"
```

Configuration can also be stored in `.autoxrd.toml` for non-secret values:

```toml
provider = "openai"
model = "mimo-v2.5-pro"
max_tokens = 8192
effort = "high"

[openai]
base_url = "https://token-plan-sgp.xiaomimimo.com/v1"
```

### 4. Start AutoXRD

Recommended development command:

```bash
.venv/bin/autoxrd --auto-approve
```

`--auto-approve` skips confirmation for model-requested commands and file writes. Use it only
inside an isolated project workspace. To retain permission prompts:

```bash
.venv/bin/autoxrd
```

One-shot usage:

```bash
.venv/bin/autoxrd -p "Run pattern QC on data/sample.xy"
.venv/bin/autoxrd -p "Review this FullProf result and explain the residual"
```

Other modes:

```bash
.venv/bin/autoxrd --resume 1       # Resume a stored session
.venv/bin/autoxrd --coordinator    # Enable background workers
.venv/bin/autoxrd --help           # Show all CLI options
```

## XRD Skills

AutoXRD discovers project skills from `.autoxrd/skills/` and user skills from
`~/.autoxrd/skills/`.

| Skill | Purpose |
|---|---|
| `/xrd-pattern-qc` | Inspect range, step, noise, peaks, metadata, and artifacts |
| `/xrd-structure-audit` | Parse, fingerprint, and audit a candidate CIF |
| `/fullprof-le-bail` | Validate and run a FullProf Le Bail initialization |
| `/fullprof-pcr-compiler` | Compile one typed action into guarded PCR codeword changes |
| `/fullprof-staged-refinement` | Plan Le Bail and staged Rietveld refinement |
| `/xrd-residual-features` | Extract deterministic observed-calculated residual features |
| `/xrd-residual-diagnosis` | Map difference-pattern morphology to controlled tests |
| `/xrd-trajectory-gate` | Test falsifiable predictions and accept or reject a transition |
| `/xrd-physical-audit` | Reject unphysical fits and rank competing hypotheses |

Examples inside the TUI:

```text
/xrd-pattern-qc data/sample.xy
/xrd-structure-audit structures/sample.cif
/fullprof-le-bail templates/sample-le-bail.pcr data/sample.dat
/fullprof-pcr-compiler runs/run_002/spec.json
/fullprof-staged-refinement data/sample.xy structures/sample.cif
/xrd-residual-features runs/run_004/residual.dat
/xrd-residual-diagnosis runs/run_004
/xrd-trajectory-gate runs/run_005/transition.json
/xrd-physical-audit runs/run_010/metrics.json
```

The core research abstraction is the Evidence-Gated Refinement Graph. Each action cites a
machine-readable feature and predicts a minimum change before the numerical backend runs. The gate
rejects a lower-Rwp result when that mechanism prediction fails or physical validity regresses.

The staged-refinement skill requires each run to preserve an auditable trajectory:

```text
runs/run_001/
├── input.pcr
├── action.json
├── output.out
├── result.prf
├── refined.pcr
├── metrics.json
└── warnings.json
```

## FullProf Backend

FullProf is an external program and is not installed by `pip`. Download the appropriate Linux,
Windows, or macOS package from the
[official FullProf downloads page](https://www2017.ill.eu/sites/fullprof/downloads.html).

After installation, expose `fp2k` either on `PATH` or through:

```bash
export AUTOXRD_FULLPROF_BIN="$HOME/path/to/fullprof/fp2k"
```

For a project-local virtual environment, a convenient link is:

```bash
ln -s "$AUTOXRD_FULLPROF_BIN" .venv/bin/fp2k
```

Smoke test:

```bash
.venv/bin/fp2k
```

The program should print the FullProf version banner and request a PCR file code.

## GSAS-II Backend

For headless scripting, follow the official GSAS-II pip workflow:

```bash
sudo apt-get install -y gfortran
git clone --depth 1 https://github.com/AdvancedPhotonSource/GSAS-II.git \
  "$HOME/.local/share/autoxrd/GSAS-II"
.venv/bin/pip install "$HOME/.local/share/autoxrd/GSAS-II[useful]"
```

Verify:

```bash
.venv/bin/python - <<'PY'
from GSASII import GSASIIscriptable as G2sc
print(G2sc.ShowVersions())
PY
```

The GUI additionally requires wxPython and desktop libraries. It is not required for AutoXRD's
headless agent workflows.

## Benchmarks

Benchmark data and generated trajectories are intentionally excluded from Git. See
[`benchmarks/README.md`](benchmarks/README.md) for dataset sources, sizes, limitations, and
interpretation.

The repository includes **AutoXRD-Bench-100 v2**, a fixed 100-case evaluation with 30 Easy
select-all questions, 40 Medium scientific reports, and 30 Hard quantitative outcome tasks. Hard
scores combine deterministic F1/MAE/RMSE-style metrics with a bounded explanation Judge component:

```bash
.venv/bin/python benchmarks/autoxrd_bench.py validate
.venv/bin/python benchmarks/autoxrd_bench.py materialize
```

See [`benchmarks/autoxrd_bench_100/README.md`](benchmarks/autoxrd_bench_100/README.md) for the
isolated Agent run, single frozen-Judge protocol, and final percentage scoring command.

### FullProf official examples

```bash
.venv/bin/python benchmarks/run_fullprof.py
```

The current manifest covers CeO2, rutile/anatase QPA, Tb2BaCoO5, PbSO4 XRD/neutron,
Si3N4 QPA, magnetite/hematite, and TOF data.

### Experimental pattern QC

Place the downloaded opXRD archive at `benchmarks/data/opxrd/opxrd.zip`, then run:

```bash
.venv/bin/python benchmarks/run_pattern_qc.py --opxrd-limit 500
```

The runner also evaluates all Dara XRDML patterns when the paper supplement is placed under
`benchmarks/data/dara/supplement/`.

### Dara reference metrics

```bash
.venv/bin/python benchmarks/analyze_dara_reference.py
```

Generated artifacts are written to `benchmarks/results/`.

## Testing

Run the full AutoXRD suite:

```bash
.venv/bin/python -m compileall -q src .autoxrd/skills
.venv/bin/pip check
.venv/bin/pytest -q --ignore=tests/test_sandbox_integration.py
```

In the prepared environment, all non-platform tests pass:

```text
358 passed
```

The separate sandbox integration suite requires permission to create Linux namespaces. In restricted
containers, `bwrap` can fail with `RTM_NEWADDR: Operation not permitted`; this does not affect XRD
analysis but must be tested on the intended deployment host.

## Data and Configuration Paths

| Purpose | Path |
|---|---|
| Global configuration | `~/.config/autoxrd/config.toml` |
| Project configuration | `.autoxrd.toml` |
| Sessions | `~/.config/autoxrd/sessions/` |
| Memory | `~/.config/autoxrd/memory/` |
| Plans | `~/.config/autoxrd/plans/` |
| User skills | `~/.autoxrd/skills/` |
| Project skills | `.autoxrd/skills/` |
| Benchmark downloads | `benchmarks/data/` |
| Benchmark results | `benchmarks/results/` |

## Scientific References

- [FullProf documentation and tutorials](https://www2017.ill.eu/sites/fullprof/documentation.html)
- [GSAS-II scripting documentation](https://gsas-ii.readthedocs.io/en/latest/GSASIIscriptable.html)
- [opXRD dataset](https://zenodo.org/records/14279434)
- [Dara source code](https://github.com/CederGroupHub/dara)
- [SimXRD-4M source code](https://github.com/Bin-Cao/SimXRD)
- [SIMPOD source code](https://github.com/BCV-Uniandes/SIMPOD)

## Security Notes

- Never commit API keys, private diffraction data, or proprietary CIF databases.
- Treat `.pcr`, `.cif`, and downloaded metadata as untrusted input at parser boundaries.
- `--auto-approve` allows shell commands and writes without confirmation.
- Keep raw measurements immutable and write preprocessing/refinement results to new paths.
- Report assumptions, unresolved ambiguity, rejected runs, and physical violations in final
  scientific outputs.
