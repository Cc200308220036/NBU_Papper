# Project semantic revision from pct_static_v1 to pct_contact_network_v2

This file is the semantic patch declaration. No downloaded or vendored upstream
file is modified; upstream byte hashes and the old compatibility.patch remain
valid. New balance_adapter.EquilibriumSpace overrides Space.check_box and
replaces the recursive impact call with balance_network.solve_network. Thus
the semantic patch is in independent project modules, not a misleading diff
pretending to have been applied to upstream.

- Preserve Box mass/density, coordinates, flag=False, actual drop height,
  contact construction, six-decimal intersections, original ConvexHull and
  10% scale_down. Retain actual commit-order geometry reconstruction.
- Replace all Box.calculated_impact branches (including direct/single/two
  support) by one simultaneous equilibrium system. Replace projected force
  centers by nonnegative forces at physical contact rectangle vertices.
- Replace recursive immediate ancestor updates by a full DAG solve. Every
  contact force appears with opposite signs on the two adjacent boxes;
  shared ancestor totals and horizontal moments are conserved simultaneously.
- Enforce ground support footprint equilibrium, whereas upstream returns True
  for floor boxes without considering their cumulative resultant.
- Retain the shrunken/perturbed non-ground hull as an extra conservative
  condition. Distinguish full physical infeasibility (independent separation
  witness required) from a conservative margin failure (UNASSESSABLE).
- No force clipping, normalization, NNLS residual surrogate, sign-only patch,
  changed hull or tolerance widening. Negative or nonfinite reactions are ERROR.
- New deterministic rule: maximum common retained-hull slack, followed by
  lexicographic force minimization in canonical contact order.
- Virtual drops/checks, setting=2 and automatic rotation flags explicitly
  rejected in v2. No upstream impact shortcut is reachable via v2 drops.
- New opt-in BalancedConfig/Result and balance_adapter.assess_candidate. Legacy
  root assess_candidate and all original tests remain v1 for honest regression
  and defect reproduction; they must not be selected for P2.

Optional dependency extra: stability = NumPy 2.1.3 and SciPy 1.15.3, with HiGHS
version and compiled-core SHA256 included in runtime identity. The LP is a
small static vertical reaction system, not a training/RL environment or a
real collapse simulation. Unknown solver statuses/nonconvergence are ERROR;
uncertified or conservative-only negatives are UNASSESSABLE.

New schemas/configs/design/these notes are package resources and part of the
v2 source digest. The public four status meanings and original BoxInput,
PlacedState, geometry bridge are reused. P2 data/task/decision binding, enabled,
monitor persistence, stop and recovery are not implemented in this revision.
