# Guarded FullProf PCR Workflow

AutoXRD does not let the LLM rewrite a PCR file. It catalogs parameters from a trusted template,
checks the supported scientific scope, freezes catalogued codewords, and compiles one typed action.

## Supported Scope

- Constant-wavelength powder XRD (`Job=0`)
- One pattern
- One or two phases
- Rietveld (`Jbt=0`) or Le Bail profile matching (`Jbt=2`)
- Space-group-generated symmetry (`Isy=0`)
- Scale, zero, polynomial background, lattice, profile, and asymmetry codewords

The compiler catalogs atomic coordinates, Biso, and occupancy for inspection, but deliberately refuses
to release them. Those actions require FullProf limit/restraint generation and refined-value parsing,
which are not yet implemented. Preferred orientation and size/strain are also outside the current
compiler claim.

## Inspect

```bash
python -m xrd.pcr inspect template.pcr > template.inspect.json
```

Inspection reports the input hash, phase controls, parameter catalog, active codeword groups, MVP
failures, and Le Bail initialization failures. An unsupported or inconsistent active codeword is a
hard failure, not a warning to bypass.

## Le Bail Initialization

The first run follows the FullProf manual's profile-matching procedure. The supplied template must
already contain `Jbt=2`, `Nat=0`, `Irf=0`, `Isy=0`, `Maxs=0`, and `Aut=0`:

```bash
python -m xrd.pcr validate-le-bail template.pcr
python -m xrd.le_bail template.pcr pattern.dat runs --case le_bail_000
```

AutoXRD refuses to derive this template by deleting atoms from a Rietveld PCR. The approximate cell,
space group, instrument model, angular range, and profile settings must be prepared and validated as
scientific inputs.

The first run leaves the source `.pcr` unchanged and writes the follow-up controls to `.new`, including
`Irf=2`. Use that `.new` file as the next immutable template and carry forward all generated base and
phase-indexed HKL files after renaming their case prefix for the child run.

## Compile One Action

Create a specification whose SHA-256 pins the immutable parent template:

```json
{
  "template": "runs/le_bail_000/le_bail_000.pcr",
  "template_sha256": "<64 hexadecimal characters>",
  "output": "runs/compiled/le_bail_001.pcr",
  "action": {
    "kind": "refine_background",
    "stage": "profile_match",
    "parameters": ["background.b0", "background.b1"],
    "rationale": "Low-angle baseline bias remains structured.",
    "evidence": [{
      "feature": "absolute_low_angle_bias",
      "value": 0.01138,
      "source": "runs/le_bail_000/residual.json",
      "threshold": ">0.005"
    }],
    "predictions": [{
      "metric": "absolute_low_angle_bias",
      "direction": "decrease",
      "minimum_change": 0.002
    }],
    "bounds": {},
    "parent_run_id": "le_bail_000"
  },
  "selectors": ["background.b0", "background.b1"]
}
```

Compile without overwriting the source:

```bash
python -m xrd.pcr compile action.json
```

The selectors must exactly equal the typed action parameters. Shared nonzero codewords are expanded as
one constraint group; a constraint that crosses the typed action family is rejected. The compiler
forces `Aut=0` so FullProf cannot silently reassign codewords. The output PCR
and `.compile.json` provenance record must enter the trajectory as artifacts.

## Residual Gate

FullProf PRF files are parsed directly:

```bash
python -m xrd.residual runs/le_bail_001/le_bail_001.prf > residual.json
```

Compare the output with the parent snapshot and apply `/xrd-trajectory-gate`. Backend return code 0,
successful compilation, or an improved targeted feature does not independently authorize acceptance.
