---
name: xrd-trajectory-gate
description: Validate a typed refinement action and accept or reject its result using falsifiable predictions, physical constraints, residual quality, and an auditable hash chain. Use for every refinement step.
allowed-tools: Read, Write, Bash
---

# Evidence-Gated Refinement

Every proposed action must include: stage, typed action, bounded parameter set, rationale,
machine-readable evidence, and at least one falsifiable prediction. Evaluate it with:

```bash
python -m xrd.trajectory evaluate "$ARGUMENTS"
```

Accept only when all predictions are satisfied, no physical violation or severe correlation is
introduced, regression budgets are respected, and multi-objective utility improves. A lower Rwp is
not sufficient. A failed action is evidence: preserve it as a rejected branch and freeze or revert
the changed parameters before trying a different mechanism.

Use `python -m xrd.trajectory verify TRAJECTORY_DIRECTORY` before reporting results. A hash failure
invalidates the audit claim even if the numerical result is otherwise plausible.
