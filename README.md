# AutoXRD

<img width="1915" height="821" alt="ChatGPT Image 2026年9月2日 14_21_08" src="https://github.com/user-attachments/assets/427a2c72-0705-488a-bfb6-b8eca2b14e65" />


AutoXRD is a terminal-based LLM agent for powder diffraction analysis and
auditable Rietveld refinement. It combines a code-agent runtime with native file
and shell tools, reusable XRD skills, scientific backends, deterministic checks,
and append-only refinement evidence.

The intended division of responsibility is:

> The LLM plans, writes workflows, and interprets evidence. Established
> crystallographic software performs numerical fitting. Deterministic checks and
> physical review decide whether a refinement state is acceptable.

AutoXRD is an agent framework, not a replacement for crystallographic software
or expert review. A lower `Rwp` alone is not treated as proof of a correct model.

## Capabilities

- Interactive terminal UI with streaming model responses and tool calls
- OpenAI-compatible and Anthropic API providers
- Native `Read`, `Write`, `Edit`, `Glob`, `Grep`, and `Bash` tools
- Session persistence, memory, context compression, plans, and permissions
- Project and user skill discovery
- Powder-pattern readers and quality-control utilities
- CIF structure inspection and physical validation
- FullProf execution, output parsing, residual extraction, and guarded PCR editing
- Headless GSAS-II workflows written and executed by the agent
- Staged refinement actions with accepted/rejected trajectory records
- Residual, convergence, correlation, occupancy, displacement, and phase-fraction checks

## Requirements

- Python 3.11 or newer
- Git
- An API key for an OpenAI-compatible or Anthropic model
- Linux or macOS for the terminal application
- FullProf and/or GSAS-II for numerical refinement

The TUI and general code-agent tools work without a crystallographic backend.
Actual Rietveld refinement requires at least one backend.

## Installation

### Clone and install

```bash
git clone https://github.com/Stephen-SMJ/AutoXRD.git
cd AutoXRD
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[xrd]"
```

For development and tests:

```bash
.venv/bin/pip install -e ".[dev,xrd]"
```

The `xrd` extra installs the scientific Python stack, including NumPy, SciPy,
pandas, Matplotlib, gemmi, pymatgen, PyCifRW, LMFit, pyFAI, FabIO,
xrayutilities, diffpy.structure, ASE, and related packages. FullProf and GSAS-II
are configured separately because they are external backends.

### Installer script

The repository also provides a user-local installer:

```bash
bash install.sh
```

It installs the base TUI under `~/.autoxrd` and creates
`~/.local/bin/autoxrd`. Install the `xrd` extra in that environment when the
scientific Python stack is required:

```bash
~/.autoxrd/.venv/bin/pip install -e "$HOME/.autoxrd[xrd]"
```

## Model Configuration

Keep API keys in environment variables or a local `.env` file. `.env` and
`.autoxrd.toml` are ignored by Git.

### OpenAI-compatible endpoint

```bash
export AUTOXRD_PROVIDER=openai
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://your-provider.example.com/v1"
export AUTOXRD_MODEL="your-model-name"
export AUTOXRD_MAX_TOKENS=8192
export AUTOXRD_EFFORT=high
```

`OPENAI_BASE_URL` may point to OpenAI or any gateway that implements the
OpenAI chat-completions tool-calling interface. Use the exact model identifier
published by that provider.

### Anthropic endpoint

```bash
export AUTOXRD_PROVIDER=anthropic
export ANTHROPIC_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://your-gateway.example.com"  # optional
export AUTOXRD_MODEL="claude-sonnet-4-6"
export AUTOXRD_MAX_TOKENS=32000
```

### TOML configuration

Non-secret settings can be stored globally in
`~/.config/autoxrd/config.toml` or per project in `.autoxrd.toml`:

```toml
provider = "openai"
model = "your-model-name"
max_tokens = 8192
effort = "high"

[openai]
base_url = "https://your-provider.example.com/v1"
```

Set the API key in the environment rather than committing it to TOML. A custom
configuration file can be selected with `--config PATH`.

Configuration precedence is:

1. CLI flags
2. Environment variables
3. Project `.autoxrd.toml`
4. Global `~/.config/autoxrd/config.toml`
5. Built-in defaults

Useful CLI overrides:

```bash
autoxrd \
  --provider openai \
  --base-url https://your-provider.example.com/v1 \
  --model your-model-name \
  --max-tokens 8192 \
  --effort high
```

See [`docs/configuration.md`](docs/configuration.md) for the complete provider
and configuration reference.

## Starting AutoXRD

Interactive mode with permission prompts:

```bash
autoxrd
```

Autonomous mode for an isolated project workspace:

```bash
autoxrd --auto-approve
```

`--auto-approve` allows model-requested shell commands and file writes without
interactive confirmation. Use it only inside a workspace whose contents may be
modified.

One-shot mode:

```bash
autoxrd --print "Inspect data/sample.xy and produce a pattern-QC report"
autoxrd --print "Refine data/pattern.xye against structures/start.cif and preserve every accepted and rejected state"
```

Session and coordinator commands:

```bash
autoxrd --resume 1
autoxrd --coordinator
autoxrd --help
```

## FullProf Configuration

FullProf is not distributed with this repository. Install it from the
[official FullProf site](https://www2017.ill.eu/sites/fullprof/downloads.html),
then expose `fp2k` using one of:

```bash
export AUTOXRD_FULLPROF_BIN="$HOME/path/to/fullprof/fp2k"
# or
export FULLPROF_BIN="$HOME/path/to/fullprof/fp2k"
# or place fp2k on PATH
```

Verify the binary before asking the agent to refine a pattern:

```bash
"$AUTOXRD_FULLPROF_BIN"
```

The guarded PCR compiler currently supports constant-wavelength, single-pattern,
one- or two-phase template families and releases only scale, zero, background,
lattice, profile, and asymmetry parameters. Atomic positions, displacement
parameters, occupancies, preferred orientation, and size/strain are represented
in the refinement schema but are not yet released through this guarded compiler.

AutoXRD can execute broader FullProf workflows through native code tools, but
direct PCR editing does not receive the compiler's selector-level guarantees.

## GSAS-II Configuration

AutoXRD uses the GSAS-II scripting API for headless workflows. One installation
method is:

```bash
git clone --depth 1 https://github.com/AdvancedPhotonSource/GSAS-II.git \
  "$HOME/.local/share/autoxrd/GSAS-II"
.venv/bin/pip install "$HOME/.local/share/autoxrd/GSAS-II[useful]"
```

Verify the scripting API:

```bash
.venv/bin/python - <<'PY'
from GSASII import GSASIIscriptable as G2sc
print(G2sc.ShowVersions())
PY
```

The desktop GSAS-II GUI is not required. Through `GSASIIscriptable`, the agent
can create projects and stage scale, background, lattice, profile, atomic,
occupancy, preferred-orientation, and microstructure refinement when supported
by the supplied data and model.

## Core XRD Skills

AutoXRD ships ten XRD skills:

| Skill | Purpose |
|---|---|
| `/xrd-pattern-qc` | Inspect scan range, step, intensity, noise, peaks, and metadata |
| `/xrd-structure-audit` | Parse and physically audit candidate structures |
| `/fullprof-le-bail` | Validate and execute FullProf Le Bail initialization |
| `/fullprof-pcr-compiler` | Compile supported typed actions into guarded PCR codewords |
| `/fullprof-staged-refinement` | Plan and review staged FullProf refinement |
| `/gsasii-executable-workflow` | Create auditable GSAS-II workflows from public inputs |
| `/xrd-residual-features` | Extract deterministic observed/calculated residual features |
| `/xrd-residual-diagnosis` | Map residual morphology to controlled next actions |
| `/xrd-trajectory-gate` | Accept or reject state transitions against predictions and checks |
| `/xrd-physical-audit` | Check cells, occupancies, displacement parameters, fractions, and correlations |

Project skills are discovered from `.autoxrd/skills/`. User-level skills can be
installed under `~/.autoxrd/skills/`. Set `AUTOXRD_SKILLS_DIR` to add an explicit
built-in skill directory.

Example requests:

```text
/xrd-pattern-qc data/sample.xy
/xrd-structure-audit structures/sample.cif
/fullprof-staged-refinement data/sample.dat structures/start.cif
/gsasii-executable-workflow data/sample.xye structures/start.cif
```

## Recommended Workspace

Run AutoXRD from a project directory and keep raw inputs immutable:

```text
project/
├── .autoxrd.toml
├── data/                 # measured patterns; treated as read-only inputs
├── structures/           # CIF or starting structural models
├── runs/                 # generated scripts, PCR/GPX states, logs, and profiles
└── artifacts/            # final reports, metrics, difference curves, and audits
```

A refinement result should preserve the backend command, backend version,
starting state, each accepted or rejected action, numerical metrics, residual
evidence, physical checks, uncertainty, and limitations.

## Testing

```bash
.venv/bin/python -m compileall -q src .autoxrd/skills
.venv/bin/pip check
.venv/bin/pytest -q
```

Linux sandbox integration tests require Bubblewrap and permission to create
namespaces. Restricted containers may need to omit those platform tests:

```bash
.venv/bin/pytest -q --ignore=tests/test_sandbox_integration.py
```

## Repository Layout

```text
AutoXRD/
├── .autoxrd/skills/      # Core XRD skill instructions and deterministic scripts
├── docs/                 # Configuration, skills, sandbox, memory, and backend docs
├── src/
│   ├── core/             # Agent engine, model clients, configuration, sessions
│   ├── features/         # Skills, plans, memory, coordinator, and sandbox
│   ├── tools/            # Native file, shell, planning, and agent tools
│   ├── tui/              # Terminal application
│   └── xrd/              # XRD schemas, parsers, validators, backends, and trajectories
├── tests/                # Core unit and integration tests
├── install.sh
└── pyproject.toml
```

For a detailed implementation map, see [`framework.md`](framework.md). FullProf
PCR behavior is documented in [`docs/fullprof-pcr.md`](docs/fullprof-pcr.md).

## Security and Scientific Use

- Never commit API keys, proprietary diffraction data, or confidential CIF files.
- Treat downloaded patterns, PCR files, CIF files, and metadata as untrusted input.
- Use `--auto-approve` only in an isolated, backed-up workspace.
- Do not overwrite raw measurements or the only copy of a starting model.
- Inspect backend warnings, covariance, residuals, and physical validity before
  accepting a lower residual metric.
- AutoXRD outputs remain model-dependent scientific analyses and require expert
  review for consequential use.

## If you find our work useful in your research, consider citing our paper by:
```
@misc{wu2026autoxrdautonomousllmagents,
      title={AutoXRD: Autonomous LLM Agents and Comprehensive Evaluation for Powder Diffraction Analysis}, 
      author={Yuetong Wu and Maojun Sun},
      year={2026},
      eprint={2609.00070},
      archivePrefix={arXiv},
      primaryClass={cond-mat.mtrl-sci},
      url={https://arxiv.org/abs/2609.00070}, 
}
```
