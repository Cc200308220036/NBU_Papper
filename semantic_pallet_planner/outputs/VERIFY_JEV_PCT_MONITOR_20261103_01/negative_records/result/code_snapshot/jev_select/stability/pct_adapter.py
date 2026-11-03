"""Fresh-state adapter to real PCT drop_box, with rejecting numerical guards.

No alternate oracle, virtual mutation, load clipping or normalization is used.
"""
from dataclasses import asdict
from importlib.resources import files
import hashlib
import math
import time

import numpy as np

from .contracts import StabilityConfig, StabilityResult, digest
from .geometry import to_kernel
from .vendor.pct.space import Space


class NumericalFailure(RuntimeError):
    pass


class UnsupportedGeometry(ValueError):
    pass


def algorithm_identity():
    root = files(__package__)
    names = ['contracts.py', 'geometry.py', 'pct_adapter.py', '__init__.py',
             'vendor/pct/space.py', 'vendor/pct/convex_hull.py', 'vendor/pct/PctTools.py',
             'vendor/pct/__init__.py', 'vendor/pct/LICENSE', 'vendor/pct/compatibility.patch',
             'vendor/pct/upstream_manifest.json', 'configs/pct_static_v1.json',
             'schemas/stability_result_v1.schema.json', 'schemas/stability_config_v1.schema.json']
    hashes = {name: hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest() for name in names}
    return {'algorithm': 'pct_static_v1', 'commit': '5e7b4238b18310af4529e0f85157d17de605850c',
            'files_sha256': hashes, 'source_digest': digest(hashes),
            'numpy_version': np.__version__, 'length_unit': 'mm', 'mass_unit': 'kg'}


def _close(a, b, cfg):
    return np.allclose(a, b, atol=cfg.mass_atol_kg, rtol=cfg.mass_rtol)


def audit(boxes, cfg, complete, previous_flows=None):
    """Check produced edges, local equivalent stacks and ground total.

    On False the recursion can stop before reaching all ground branches: global
    ground conservation is meaningful only for a completed stable propagation.
    Every produced outgoing distribution is still checked on False.
    """
    rows = []
    for box in boxes:
        stack = box.thisStack
        if not np.isfinite([box.mass, stack.mass, *stack.centre]).all():
            raise NumericalFailure('NONFINITE_STACK')
        expected_mass = box.mass + sum(s.mass for s in box.up_edges.values())
        expected_moment = box.mass*box.centre + sum((s.mass*s.centre for s in box.up_edges.values()), start=np.zeros(3))
        if complete and (not _close(expected_mass, stack.mass, cfg) or not np.allclose(expected_moment/expected_mass, stack.centre, atol=cfg.height_tolerance_mm, rtol=0)):
            raise NumericalFailure('LOCAL_STACK_INCONSISTENT')
        flows = [e.box.up_edges[box] for e in box.bottom_edges if box in e.box.up_edges]
        for flow in flows:
            if not np.isfinite([flow.mass, *flow.centre]).all():
                raise NumericalFailure('NONFINITE_FLOW')
            if flow.mass < 0:  # no clipping, even a small negative is reported
                raise NumericalFailure('NEGATIVE_FLOW')
        signature = [(float(s.mass), tuple(s.centre)) for s in flows]
        flow_updated = signature != (previous_flows or {}).get(box, [])
        if flows and (complete or flow_updated):
            if len(flows) != len(box.bottom_edges) or not _close(sum(s.mass for s in flows), stack.mass, cfg):
                raise NumericalFailure('FLOW_MASS_NOT_CONSERVED')
        elif complete and box.bottom_edges:
            raise NumericalFailure('MISSING_FLOW')
        rows.append({'mass_kg': float(box.mass), 'center_mm': box.centre.tolist(),
                     'corner_mm': box.vertex_low.tolist(), 'vertex_high_mm': box.vertex_high.tolist(),
                     'stack_mass_kg': float(stack.mass), 'stack_center_mm': stack.centre.tolist(),
                     'support_indices': [boxes.index(e.box) for e in box.bottom_edges],
                     'outgoing_mass_kg': [float(s.mass) for s in flows],
                     'support_hull_mm': box.bottom_whole_contact_area})
    ground = sum(b.thisStack.mass for b in boxes if not b.bottom_edges)
    total = sum(b.mass for b in boxes)
    if complete and not _close(ground, total, cfg):
        raise NumericalFailure('GROUND_MASS_NOT_CONSERVED')
    return {'boxes': rows, 'input_total_mass_kg': float(total),
            'ground_mass_kg': float(ground), 'global_conservation_checked': complete}


class GuardedSpace(Space):
    """Capture real check entry and reject degeneracy without changing its math."""
    def check_box(self, max_h, box_now, setting, virtual=False):
        if setting != 1 or virtual:
            raise NumericalFailure('FORBIDDEN_KERNEL_PATH')
        self.attempt = box_now
        if max_h >= 1e-6:
            points = np.asarray(box_now.bottom_whole_contact_area, dtype=float)
            if points.ndim != 2 or points.shape[0] < 3 or points.shape[1] != 2 or not np.isfinite(points).all():
                raise UnsupportedGeometry('DEGENERATE_SUPPORT')
            area2 = abs(np.dot(points[:, 0], np.roll(points[:, 1], 1)) - np.dot(points[:, 1], np.roll(points[:, 0], 1)))
            if area2 <= 1e-12 or any(e.area[2] <= e.area[0] or e.area[3] <= e.area[1] for e in box_now.bottom_edges):
                raise UnsupportedGeometry('DEGENERATE_SUPPORT')
        result = super().check_box(max_h, box_now, setting, virtual)
        return result


def assess_candidate(placed_state, candidate, config=None):
    start = time.perf_counter()
    cfg = config if config is not None else StabilityConfig()
    # Invalid configuration is a caller/startup error; never invoke PCT for it.
    if not isinstance(cfg, StabilityConfig):
        raise ValueError('EXPECTED_STABILITY_CONFIG')
    cfg.__post_init__()
    ident = algorithm_identity()
    state_hash = candidate_hash = None
    baseline = 'NOT_ASSESSED'; first_bad = None; delta = None; evaluated = None
    calls = 0; diagnostics = {}; active = None

    def result(status, reason):
        def serial(value):
            if isinstance(value, float) and not math.isfinite(value): return repr(value)
            if isinstance(value, dict): return {k: serial(v) for k,v in value.items()}
            if isinstance(value, (list, tuple)): return [serial(v) for v in value]
            return value
        return StabilityResult(status, reason, state_hash, candidate_hash,
            getattr(candidate, 'item_id', None) if isinstance(getattr(candidate, 'item_id', None), str) else None, digest(asdict(cfg)), ident, baseline,
            first_bad, None, delta if delta is None or math.isfinite(delta) else None, evaluated, calls, serial(diagnostics), time.perf_counter()-start)

    try:
        placed_state.validate(); candidate.validate()
        if candidate.item_id in {b.item_id for b in placed_state.placed}:
            raise ValueError('DUPLICATE_ITEM_ID')
        state_hash = digest(asdict(placed_state)); candidate_hash = digest(asdict(candidate))
        space = GuardedSpace(*placed_state.container_mm, holder=len(placed_state.placed)+2)
        # A real drop can mutate ancestors before returning False. This private
        # space is discarded after the call and never shared with another candidate.
        with np.errstate(divide='raise', invalid='raise', over='raise', under='ignore'):
            for index, box in enumerate((*placed_state.placed, candidate)):
                is_candidate = index == len(placed_state.placed)
                active = 'candidate' if is_candidate else 'prefix'
                first_bad = None if is_candidate else box.item_id
                if is_candidate:
                    baseline = 'STABLE'
                geo = to_kernel(box, placed_state.container_mm)
                lx, ly, z = geo['corner_mm']; sx, sy, sz = geo['size_mm']
                # Strict project-domain checks separate out-of-domain from False
                # stability. No clipping to fit the container.
                if min(lx, ly, z) < 0 or lx+sx > space.plain_size[0] or ly+sy > space.plain_size[1] or z+sz > space.height:
                    if not is_candidate: baseline = 'UNASSESSABLE'
                    return result('UNASSESSABLE', 'OUT_OF_BOUNDS' if is_candidate else 'BASELINE_OUT_OF_BOUNDS')
                max_h = float(space.interSect2D(np.array([-lx,-ly,lx+sx,ly+sy,0]))[0])
                delta = max_h-z
                evaluated = {'item_id': box.item_id, 'kernel_corner_mm': [lx,ly,max_h],
                             'original_bottom_center_mm': list(box.bottom_center_mm),
                             'oriented_size_mm': list(box.size_mm), 'density_kg_mm3': geo['density_kg_mm3']}
                if abs(delta) > cfg.height_tolerance_mm:
                    if not is_candidate: baseline = 'UNASSESSABLE'
                    return result('UNASSESSABLE', 'POSE_HEIGHT_MISMATCH' if is_candidate else 'BASELINE_POSE_HEIGHT_MISMATCH')
                previous_flows = {b: [(float(e.box.up_edges[b].mass), tuple(e.box.up_edges[b].centre))
                    for e in b.bottom_edges if b in e.box.up_edges] for b in space.boxes}
                space.attempt = None
                calls += 1
                ok = space.drop_box(box.size_mm, (lx,ly), False, geo['density_kg_mm3'], cfg.setting)
                kernel_box = space.attempt
                if kernel_box is None:
                    raise NumericalFailure('KERNEL_REJECTED_BEFORE_STABILITY')
                if not _close(kernel_box.mass, box.mass_kg, cfg) or not np.allclose(kernel_box.centre, geo['center_mm'], atol=cfg.height_tolerance_mm, rtol=0):
                    raise NumericalFailure('BOX_MASS_OR_CENTER_MISMATCH')
                if not np.allclose(kernel_box.vertex_low, [lx,ly,z], atol=cfg.height_tolerance_mm, rtol=0) or not np.allclose(kernel_box.vertex_high, [lx+sx,ly+sy,z+sz], atol=cfg.height_tolerance_mm, rtol=0):
                    raise NumericalFailure('BOX_VERTEX_MISMATCH')
                boxes = space.boxes if ok else [*space.boxes, kernel_box]
                diagnostics = {'raw_kernel': [{'mass_kg': float(b.mass),
                    'stack_mass_kg': float(b.thisStack.mass), 'stack_center_mm': b.thisStack.centre.tolist(),
                    'outgoing_mass_kg': [float(e.box.up_edges[b].mass) for e in b.bottom_edges if b in e.box.up_edges]}
                    for b in boxes], 'kernel_return': bool(ok)}
                diagnostics.update(audit(boxes, cfg, bool(ok), previous_flows))
                diagnostics['restored_order'] = [b.item_id for b in placed_state.placed[:index]]
                diagnostics['kernel_return'] = bool(ok)
                if not ok:
                    if is_candidate:
                        return result('UNSTABLE', 'PCT_STATIC_INSTABILITY')
                    baseline = 'UNSTABLE'
                    return result('UNASSESSABLE', 'BASELINE_UNSTABLE')
        first_bad = None
        return result('STABLE', 'PCT_STATIC_STABLE')
    except UnsupportedGeometry as exc:
        if active == 'prefix': baseline = 'UNASSESSABLE'
        return result('UNASSESSABLE', str(exc))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
        diagnostics = {**diagnostics, 'stage': active or 'input', 'exception_type': type(exc).__name__, 'detail': str(exc)}
        if active:
            if active == 'prefix': baseline = 'ERROR'
            return result('ERROR', 'KERNEL_OR_ADAPTER_ERROR')
        return result('UNASSESSABLE', 'INVALID_INPUT')
    except Exception as exc:
        diagnostics = {**diagnostics, 'stage': active or 'kernel', 'exception_type': type(exc).__name__, 'detail': str(exc)}
        if active == 'prefix': baseline = 'ERROR'
        return result('ERROR', str(exc) if isinstance(exc, NumericalFailure) else 'KERNEL_NUMERICAL_ERROR')
