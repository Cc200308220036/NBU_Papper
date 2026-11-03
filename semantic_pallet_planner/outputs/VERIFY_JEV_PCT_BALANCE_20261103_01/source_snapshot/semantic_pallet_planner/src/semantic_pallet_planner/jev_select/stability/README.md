# Independent PCT static stability kernel (P0/P1)

Public entry: `assess_candidate(PlacedState, BoxInput, StabilityConfig=None)`.
All imports below are package imports; no order runner, Gym, Torch or old
geometry/capacity oracle is imported. Importing `stability` alone is lazy.

```python
from semantic_pallet_planner.jev_select.stability import (
    BoxInput, PlacedState, StabilityConfig, assess_candidate)
state = PlacedState((1000, 800, 1000), (
    BoxInput('base', (60, 200, 100), 1, (0, 0, 0)),
    BoxInput('shelf', (200, 200, 100), 1, (0, 0, 100)),
))
candidate = BoxInput('top', (100, 100, 100), 10, (60, 0, 200))
result = assess_candidate(state, candidate, StabilityConfig())
assert result.status == 'UNSTABLE'  # shelf COM shifts beyond narrow base
print(result.to_dict())
```

Input fields: container `(length,width,height)` mm; `placed` in **actual commit
order**; box `item_id`, original `(length,width,height)` `dimensions_mm`, actual
`mass_kg`, pallet-center `(x,y,z_base)` `bottom_center_mm`, yaw 0/90. Uniform
single-box mass, geometric COM and rigid cuboids only. No arbitrary/signed
angle transform is certified. Size is rotated once; kernel flag=False. Corner
x=x_world+L/2-size_x/2, y similarly; density=mass/rotated_volume kg/mm³.

`geometry.box_from_runtime(obj)` bridges existing physical object fields;
`geometry.state_from_runtime(state)` preserves the `placed_items` list order.
Callers must explicitly resolve the selected action and its actual object mass;
no future task or unarrived items belong here. Existing area-share/C fields are
ignored and never modified. This assesses stability, not capacity/stackability.

`StabilityConfig` freezes algorithm pct_static_v1, setting=1, height tolerance
1e-6 mm, mass atol=1e-9 kg and rtol=1e-9. Invalid config raises ValueError before
any kernel call. Default config resource is `configs/pct_static_v1.json`;
construct with `StabilityConfig(**json.loads(resource.read_text()))`.
Config has no enabled field: the future outer monitor owns the unique
`stability_monitor.enabled`, default false. No monitor or execution CLI exists
in this delivery.

Each assessment validates input, creates a new Space with len(placed)+2 holder,
restores order by real checked drops, compares automatic drop height **before**
placing, calls actual PCT drop and checks mass/COM/vertices. It discards the
Space even after failure; no cache or shared mutable kernel state. Frozen value
contracts accept tuple data; mutable inputs are read only, never changed.

Result fields: `status`, `reason_code`, `state_digest`, `candidate_digest`,
`candidate_id`, `config_digest`, `algorithm_identity` (commit, source/resource
hashes and NumPy version), `baseline_status`, `first_bad_prefix`,
`failed_item_id`, `height_delta_mm`, `evaluated_pose`, `kernel_calls`,
`diagnostics`, `duration_s`, `version`. `to_dict()` produces JSON values;
canonical digests use project-compatible sorted compact UTF-8 JSON, no NaN.
Duration is wall time for one independent assessment, not paper complexity.

- STABLE/PCT_STATIC_STABLE: prefix and candidate accepted by PCT and guards.
- UNSTABLE/PCT_STATIC_INSTABILITY: stable prefix, exact candidate height,
  actual PCT False on static stability. Does not mean real collapse.
- UNASSESSABLE: illegal/unsupported input or domain, height mismatch,
  degenerate support, or BASELINE_UNSTABLE. A bad prefix is never attributed
  to the candidate. `first_bad_prefix` identifies the first unrecoverable box.
- ERROR: numerical failure/nonfinite result, negative flow, conservation
  failure or kernel/adapter exception. Exception stage/type/code is retained.

`failed_item_id` is null: upstream False does not reliably locate the failed
ancestor. Diagnostics list support indices in restoration order, box and
combined mass/COM, hull, outgoing flows, global totals, real kernel return.
No probability or invented moment is provided. Error diagnostics preserve raw
flow counterexamples; nonfinite raw diagnostic numbers use explicit strings
(e.g. 'nan'), never a valid numerical result. On False, recursion may end early:
check all produced flow finiteness/negativity and changed distributions;
global/local completed propagation conservation is asserted only for True.
Reject a support hull with fewer than 3 vertices or absolute doubled area
<=1e-12 mm²; reject zero/negative contact extents. These are rejecting
degeneracy guards, not a replacement hull. Completed local COM consistency
uses absolute 1e-6 mm, zero relative tolerance. No clipping, normalization,
support hull replacement or fallback oracle.

See vendor/pct/UPSTREAM.md for the unmodified numerical assumptions, source
identity, compatibility patch and known general multisupport LS defect. The
symmetric two-support and direct three-support branches pass constructed
checks; general LS support is **not established** and its counterexample
returns ERROR. This limitation is not a stable acceptance of that geometry.

Future target two: resolve an already selected exact action into BoxInput,
freeze config+algorithm identity, persist selection then this result before
commit, and implement STABLE commit / other-status termination and recovery.
Bind data/task/decision/original-artifact/old-physics outside this kernel;
never feed labels back to candidate generation, scoring, ranking or prompts.
Do not rewrite historical source identities after adding this module.

Validation from repository root (disable unrelated host ROS pytest plugins):

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=semantic_pallet_planner/src \
  python -m pytest -q semantic_pallet_planner/tests/unit/test_stability_kernel.py
```

No runtime monitor, checkpoints, order smoke, historical replay, candidate
filtering, physical admission changes, remote model, keys, training or weights.

## P1.1 opt-in corrected kernel (2026-11-03)

The preceding v1 API remains the reproducible legacy adapter, including its
known upstream failure. For the corrected project semantic revision use:

```python
from semantic_pallet_planner.jev_select.stability.balance_adapter import assess_candidate
from semantic_pallet_planner.jev_select.stability.balance_contracts import load_config
result = assess_candidate(state, candidate, load_config())
assert result.algorithm_identity['algorithm'] == 'pct_contact_network_v2'
```

Input BoxInput/PlacedState and runtime geometry bridges are unchanged. New
BalancedResult has version pct_stability_result_v2 and the same four statuses.
The configuration resource is configs/pct_contact_network_v2.json, schemas
are stability_config_v2/stability_result_v2. Optional dependency extra
`stability` pins NumPy2.1.3/SciPy1.15.3; runtime identity hashes solver code and
compiled HiGHS core. Package import alone remains lazy and does not load SciPy.

See [BALANCE_DESIGN.md](BALANCE_DESIGN.md) and
[BALANCE_CHANGES.md](BALANCE_CHANGES.md). All support counts share one global
reaction system; no original impact split or virtual path is used. Stable
results include reactions, local/global mass and horizontal-moment residuals,
physical feasibility witness, solver phases, retained hulls and frozen
tolerances. Infeasibility requires a checked separation witness before
UNSTABLE; conservative hull or strict-interior boundary failure is
UNASSESSABLE, solver/nonfinite/negative/residual failure is ERROR.

The selector requires a positive common reaction/hull interior margin. Exact
zero-reaction boundary equilibria and extremely small normalized margins may
therefore be UNASSESSABLE; this is not physical instability. No real-order
coverage or performance claim is established. Actual masses and positions,
setting=2 rejection, fresh per-candidate state and independent capacity/area
ledger remain unchanged. P2 must explicitly freeze/select v2 and refuse any
fallback to v1; no monitor, scheduling, stop, CLI or recovery is added here.
