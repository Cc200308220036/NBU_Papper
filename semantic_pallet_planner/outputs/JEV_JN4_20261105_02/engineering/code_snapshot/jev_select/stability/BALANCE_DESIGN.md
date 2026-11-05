# P1.1 algorithm design — pct_contact_network_v2

Design frozen before implementation, 2026-11-03. This is a project semantic
revision, not unmodified PCT. The old pct_static_v1 and its failure artifacts
remain available for reproduction only. No upstream download files are edited.

## Model and geometry

Retain real PCT Space.drop_box contact construction, intersection rounding to
6 decimal places, x+=y*1e-6 hull perturbation, 10% hull contraction about vertex
mean, mm/kg and original height checks. A positive-area horizontal contact
rectangle transmits nonnegative vertical reactions at its four physical
vertices. Four corner reactions represent every possible resultant inside
that entire rectangle, including its boundary; contact-center-only splitting
is not used. Ground reactions use the actual floor-box footprint vertices.
Gravity is common and cancels, so forces are expressed as equivalent kg.
Uniform rigid boxes, vertical gravity only: no friction/sliding or dynamics.

For each box i simultaneously enforce outgoing minus incoming mass = own
mass, and outgoing minus incoming horizontal moments = own mass times own
horizontal center. Each force appears once with opposite signs on upper and
lower boxes. Ground is an external sink. This is a global contact-network LP,
not greedy local recursive splitting. All contacts are generated before the
solve; no ancestor's partial load is inspected. Each prefix is solved from
scratch in actual commit order. Shared ancestors therefore receive the sum
of all branches exactly once. Single/two/many contacts use the same model.

The original contracted/perturbed support hull is an additional conservative
resultant constraint for every non-ground box. Physical contact vertices are
not shifted or contracted. Both geometry assumptions are preserved explicitly;
they are not silently combined into a new support area.

## Scaling, deterministic selection and numerical checks

Normalize force by total own mass T, moments by a common horizontal container
scale L, and center each box's moment equations on its own center. Canonically
sort rows by item_id and force columns by (upper_id,lower_id,x,y). Sorting
solver rows/contacts does not reorder actual box restoration. On this acyclic
load network every normalized reaction is bounded by 1, so bounds are [0,1].

1. Find feasibility on the complete physical contact network without the
   conservative hull constraints.
2. If feasible, add retained hull halfplanes and maximize their common
   dimensionless interior slack t (0<=t<=1), also bounded by every normalized
   reaction f_j. Thus the selector searches for a strict interior of both the
   reaction cone and the retained hull. Hull slack is force-distance/T/L,
   not an extra geometric contraction.
3. Freeze maximal t, then lexicographically minimize every force in canonical
   order, freezing each optimum as an equality. This defines a deterministic
   multi-solution rule; no post-normalization/clipping is allowed. Solver and
   dependency versions are part of algorithm identity.
4. Audit the returned forces independently of solver success: finite and
   nonnegative values, per-box mass and two moments, every force/point, hull
   inclusion, and whole-network ground mass and two moments. Emit physical
   units, tolerances, solver phases/statuses and residuals. No in-place writes
   to the packaging capacity/area-load ledger or original inputs.

Frozen tolerances: existing height 1e-6 mm, mass atol 1e-9 kg and rtol 1e-9;
new moment atol 1e-6 kg*mm and rtol 1e-9; HiGHS primal/dual feasibility 1e-10;
scaled audit 1e-9; strict hull interior slack >1e-10. These are new declared
numerical assumptions, not relaxed v1 tolerances. Nonfinite/negative flow or
failed residual audit is ERROR. Very small/boundary cases may be UNASSESSABLE.

## Negative conclusions and unsupported paths

A local split failure never establishes instability. Even global LP status
'infeasible' alone is insufficient: independently check a bounded Farkas
separation witness on the physical matrix A f=b, 0<=f<=1. For a supplied y,
a feasible vector must satisfy b·y >= sum(min((A^T y)_j,0)). A strictly positive
separation gap (threshold 1e-8) certifies physical network infeasibility under
the declared discrete contact model. Only that certificate yields UNSTABLE.
This check does not alter/clip a force vector. Uncertified infeasibility is
UNASSESSABLE; solver failures/nonconvergence are ERROR.

If physical equilibrium exists but the conservative contracted hull cannot be
satisfied, or only a hull boundary solution is certified, return UNASSESSABLE
with a margin-specific reason, not physical instability. No claim about real
collapse is made. Degenerate/non-positive contact areas, duplicate contact
records and invalid topology are explicitly rejected. Collinear support
centers are allowed when their actual contact rectangles have positive area.

The corrected Space.check_box bypasses all upstream recursive impact and
single/two-support shortcuts. setting=2, non-false rotation flags, and virtual
drops/checks are explicitly rejected. Only real checked drops in a disposable
Space are supported. There is no fallback to old oracle or v1 splitting.

## Version and acceptance

New explicit API: stability.balance_adapter.assess_candidate with
BalancedConfig, algorithm pct_contact_network_v2; root default v1 stays legacy
so old tests and provenance remain distinguishable. P2 must explicitly select
v2, never the legacy default. Dependencies: NumPy and optional SciPy (tested
local SciPy 1.15.3/HiGHS). No RL/Gym/weights. Separate config/result schemas,
resource/source/dependency hashes and semantic change notes are delivered.

R01–R10 use analytic geometry/moments and independent checks, including the
unchanged upstream 3kg counterexample, asymmetric 3, >=4 supports, full contact
area vs center hull, boundary/degeneracy, impossible networks, heterogeneous
masses, shared ancestors, permutation/isolation and non-source wheel loading.
A design or test count is not acceptance: only saved actual physical results
can close P1 in this explicitly bounded model. P2 integration remains NOT_RUN.

## Development design refinement before final freeze

The initial hull-slack-only selector produced a -4.6e-12 solver reaction on a
shared-ancestor fixture and correctly returned ERROR. The failed vector and
initial design/source are retained in outputs/development_max_hull_only.
The revised selector adds t<=f_j for every force, maximizing a common network
interior margin before lexicographic choice. These inequalities choose an
interior solution, not new force/moment tolerances. They never clip a vector.
A physical equilibrium requiring a structurally zero reaction has t=0 and is
explicitly UNASSESSABLE/NETWORK_INTERIOR_BOUNDARY, even if it has a valid
non-strict solution. This is a declared boundary coverage limit, not proof of
instability; general 3/4/many-support interiors must still pass physically.

HiGHS presolve is frozen off for the v2 LP sequence. Development with presolve
on failed on redundant lexicographic equalities in the heterogeneous shared
ancestor fixture (HiGHS status 15 / SciPy status4), correctly producing ERROR.
Disabling presolve preserves the same equations, bounds and tolerances; it is
a solver setting, not a retry/fallback. Both development JUnit reports remain
saved. The final selector uses highs-ds, presolve=False for every phase.
