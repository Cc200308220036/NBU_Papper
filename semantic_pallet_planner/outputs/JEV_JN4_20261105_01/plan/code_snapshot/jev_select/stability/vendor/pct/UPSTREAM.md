# PCT source identity and adaptation

Read-only source: `/home/cyw/NBU_Papper/Online-3D-BPP-PCT`.
Repository: https://github.com/alexfrom0815/Online-3D-BPP-PCT
Expected and actual HEAD: `5e7b4238b18310af4529e0f85157d17de605850c`.
Local upstream worktree was clean. No fetch, checkout, update or upstream edits.
`upstream_manifest.json` gives raw-byte upstream and adapted hashes; LICENSE is
copied byte-for-byte (MIT, Copyright (c) 2026 Hang Zhao).

Three original modules retained, including unused space-maintenance helpers:
`space.py`, `convex_hull.py`, `PctTools.py`. Their import graph requires only
NumPy plus Python stdlib. Original `PctContinuous0/__init__.py` is deliberately
not copied: it imports the RL/Gym environment. Both new package initializers
are inert. `compatibility.patch` is the entire code compatibility change:
`astype(np.float)` becomes `astype(float)`. Original line endings of unchanged
modules are retained. No global NumPy monkey patch. The adapter separately adds
input checks, numerical rejection guards and diagnostics; it does not replace
hull, recursive COM propagation or flow calculations.

Code source is the PCT author repository. The repository also includes a
stability approximation associated with other work: adopting these modules
is not a reproduction or validation of an entire PCT paper. The method paper
linked by the project specification is https://arxiv.org/abs/2108.13680;
this delivery evaluates local code behavior only and does not infer paper
accuracy, complexity or performance from it.

Numerical semantics retained: mm and kg; `interSect2D` rounds intersections to
6 decimal places (1e-6 mm resolution); hull perturbs x by y*1e-6 (at y=800mm,
x shifts by 0.0008mm); hull is then shrunk 10% toward the mean of hull vertices.
Upstream 1e-6 constants are used in mm comparisons and strict center contact;
point-on-edge returns False. Floating-point slope/infinity logic and `lstsq`
are unchanged. NumPy 2.x warns about 2D `np.cross`; warning retained, not hidden.
`setting=1` and real `drop_box(flag=False)` only. `setting=2` is forbidden by
configuration and check-entry guards. No virtual-drop path or EMS search runs.

The two-support projection is approximate and not a full equilibrium solver;
multisupport least squares can yield negative or nonconserved flow. A saved
three-support counterexample returns upstream True but violates conservation;
adapter returns ERROR, never clips/renormalizes or calls the old oracle.
No semantic fix is included; general least-squares multisupport reliability
remains unestablished. See the independent acceptance report and fixture.

## Project P1.1 opt-in semantic revision (2026-11-03)

The preceding statements describe legacy pct_static_v1, retained for honest
reproduction. Project algorithm pct_contact_network_v2 now replaces impact
splitting through separate balance_adapter/balance_network modules; none of
these upstream source files is edited. See ../../BALANCE_DESIGN.md and
../../BALANCE_CHANGES.md for the explicit physical/solver contract and diff
scope. P2 must use the v2 entry/config and may not fall back to legacy v1.
