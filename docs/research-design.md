# AutoXRD Research Design

## Research Thesis

AutoXRD tests a narrower and more defensible claim than "an LLM can perform Rietveld
refinement":

> A scientific agent is more reliable when every numerical intervention is typed,
> evidence-gated, falsifiable, physically validated, and preserved as an auditable trajectory.

The unit of evaluation is therefore not only the final structure. It is the complete decision
trajectory, including rejected runs, evidence used, parameters released, predictions made, backend
outputs, and physical checks.

## Evidence-Gated Refinement Graph

The central representation is an Evidence-Gated Refinement Graph (EGRG). A node is a complete fit
snapshot. A directed edge is one bounded refinement intervention. An edge contains:

```text
Action = {
  stage,
  action_kind,
  bounded_parameters,
  evidence,
  rationale,
  falsifiable_predictions,
  parent_run_id
}
```

For example, a nearly angle-independent peak displacement may justify refining zero shift alone.
Before the backend runs, the agent must predict a minimum reduction in an absolute position-bias
feature. A lower Rwp without that predicted reduction does not support the proposed mechanism.

This separates three questions that are often conflated:

1. Did the optimizer find a numerically better point?
2. Did the intervention improve the residual feature it was intended to explain?
3. Is the resulting model physically and statistically admissible?

Only an edge satisfying all three is accepted into the main trajectory. Rejected edges remain in
the experiment record and provide supervision for policy learning and skill distillation.

## Acceptance Rule

The hard gate rejects a transition if it introduces a physical violation, exceeds the Rwp or
unexplained-peak regression budget, produces severe parameter correlation, violates the stage
curriculum, or fails any declared prediction. Among hard-valid states, a scale-stable utility ranks
fit ratio, residual structure, unexplained peaks, model complexity, and correlation.

The scalar utility is only an ordering mechanism. It cannot compensate for a hard failure. This is
important because an unconstrained weighted score can hide an impossible occupancy or displacement
factor behind a small Rwp improvement.

## Scientific Contracts

The implementation defines stable contracts in `src/xrd/schemas.py`:

- `Evidence`: a feature, value, artifact source, and decision threshold.
- `FalsifiablePrediction`: a metric direction and minimum effect size.
- `RefinementAction`: one typed, bounded intervention.
- `FitSnapshot`: fit, residual, physical, uncertainty, and complexity state.
- `GateDecision`: acceptance, mechanism support, prediction outcomes, and reasons.

Every accepted or rejected transition is serialized into an append-only SHA-256 hash chain. Backend
artifacts referenced by a transition are hashed as well. The chain is not a security boundary
against a malicious operator; it is a reproducibility check that makes silent post-hoc alteration
detectable.

## Architecture

```text
raw pattern + metadata + candidate CIF
              |
              v
   QC and structure boundary audit
              |
              v
    deterministic feature extractors
              |
              v
 LLM proposes one typed intervention
              |
              v
 static stage/coupling/bounds validator
              |
              v
 FullProf / GSAS-II / BGMN execution
              |
              v
 residual features + physical validator
              |
              v
 evidence gate -> accept / reject / branch
              |
              v
 hash-chained trajectory and report
```

The LLM never receives authority to declare scientific acceptance. It proposes actions and explains
evidence; deterministic code validates transitions and crystallographic software performs numerical
optimization.

## Current FullProf Boundary

The guarded compiler uses comment-anchored semantic slots rather than unrestricted text edits. It
supports early-stage scale, zero, polynomial background, lattice, profile, and asymmetry actions for
single-pattern, constant-wavelength, one- or two-phase PCR templates. Shared codewords are preserved as
constraint groups, every parent is hash-pinned, and selectors must match the typed action exactly.

High-risk structure, occupancy, displacement, orientation, and size/strain actions remain disabled
until the compiler can emit FullProf limits/restraints and the parser can audit refined values and
uncertainties. This boundary prevents parser coverage from being misrepresented as scientific support.

## Evaluation Protocol

### Task families

1. Known-phase, single-pattern refinement from pattern, CIF, and instrument metadata.
2. Controlled artifact diagnosis: zero shift, background distortion, broadening, preferred
   orientation, noise, and impurity peaks.
3. Two-phase and three-phase identification with distractor structures.
4. Quantitative phase analysis and microstructure tasks with applicable reference values.

### Baselines

- Fixed FullProf template and one-shot refine-all.
- Hand-coded staged policy without an LLM.
- LLM direct PCR editing.
- LLM with tools but without evidence gates.
- Black-box or Optuna action search under the same backend-call budget.
- Full AutoXRD.

All methods receive identical starting structures, metadata, compute budgets, and backend versions.
Dataset splits must group by structure prototype or composition family to prevent near-duplicate
leakage.

### Outcome metrics

- Backend success, convergence, invalid-input rate, runtime, and backend calls.
- Rwp/Rexp, residual structure, unexplained-peak recall, and reference parameter error.
- Hard physical violation rate, uncertainty coverage, and severe-correlation rate.
- Correct phase-set top-k recall and calibrated hypothesis confidence.

### Trajectory metrics

- Valid-action rate and stage-order violations.
- Evidence-to-action consistency.
- Prediction satisfaction and calibration by action type.
- Regret relative to the best state observed under the same call budget.
- Recovery rate and calls-to-recovery after a deliberately bad intervention.
- Reproducibility: identical inputs yield equivalent typed actions and accepted scientific state.

### Statistical reporting

Report paired bootstrap confidence intervals across tasks, effect sizes, and failure categories rather
than only aggregate means. Pre-register primary metrics: physical violation rate and successful
known-phase refinement under a fixed backend-call budget. Treat Rwp as a secondary metric. Report
results by synthetic versus experimental data and never use simulated ground truth to imply real-data
identifiability.

## Required Ablations

1. Remove typed actions and allow direct PCR editing.
2. Remove falsifiable predictions while retaining the staged policy.
3. Remove the physical hard gate and rank by Rwp only.
4. Remove residual features and expose only scalar refinement metrics.
5. Remove rejected branches from context and memory.
6. Replace the LLM planner with the fixed rule policy.
7. Distill the planner into a smaller model with and without rejected-edge supervision.

These ablations isolate whether the contribution comes from the language model, expert curriculum,
deterministic features, physical constraints, or trajectory representation.

## Skill Distillation

The graph naturally generates preference data. For the same parent node, an accepted edge is a
positive action and a rejected edge is a mechanism-specific negative action. Distillation should use
typed state summaries, not raw hidden chain-of-thought. Training targets are the action kind,
parameters, bounds, cited evidence, prediction, and stop/escalate decision.

Evaluate the distilled policy on held-out structure families and instrument conditions. A smaller
policy is acceptable only if physical violation rate, calibration, and recovery behavior remain
within pre-declared margins; matching average Rwp alone is insufficient.

## Scope Boundaries

The first publishable system supports constant-wavelength, non-magnetic, single-pattern, one- or
two-phase tasks with validated CIF inputs and a limited profile-function family. Magnetic refinement,
ab initio structure solution, total scattering, and arbitrary vendor binary formats remain outside
the first claim. Explicit scope is more credible than unvalidated breadth.
