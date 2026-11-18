"""Opt-in v2 PCT geometry adapter with global, conserved reaction splitting."""
from dataclasses import asdict
from importlib.resources import files
import hashlib
import math
import time

import numpy as np
import scipy
import scipy.optimize._highspy._core as highs_core

from .contracts import digest
from .geometry import to_kernel
from .balance_contracts import BalancedConfig, BalancedResult
from .balance_network import (Node, Contact, solve_network, BalanceNumericalError,
                              BalanceUnsupported)
from .vendor.pct.space import Space


def algorithm_identity():
    root = files(__package__)
    names = ['balance_contracts.py','balance_network.py','balance_adapter.py',
        'contracts.py','geometry.py','__init__.py','vendor/__init__.py',
        'vendor/pct/__init__.py','vendor/pct/space.py','vendor/pct/convex_hull.py',
        'vendor/pct/PctTools.py','vendor/pct/LICENSE','vendor/pct/upstream_manifest.json',
        'vendor/pct/compatibility.patch','vendor/pct/UPSTREAM.md','BALANCE_DESIGN.md','BALANCE_CHANGES.md',
        'configs/pct_contact_network_v2.json','schemas/stability_config_v2.schema.json',
        'schemas/stability_result_v2.schema.json']
    hashes = {name:hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest() for name in names}
    binary = files('scipy.optimize._highspy').joinpath(highs_core.__file__.split('/')[-1])
    dependencies = {'numpy':np.__version__,'scipy':scipy.__version__,
                    'highs_version':'.'.join(str(getattr(highs_core,'HIGHS_VERSION_'+k)) for k in ['MAJOR','MINOR','PATCH']),
                    'highs_core_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
                    'scipy_python_sha256':{name:hashlib.sha256(files('scipy.optimize').joinpath(name).read_bytes()).hexdigest()
                        for name in ['_linprog.py','_linprog_highs.py']}}
    return {'algorithm':'pct_contact_network_v2',
        'upstream_commit':'5e7b4238b18310af4529e0f85157d17de605850c',
        'semantic_revision':'project_global_contact_reaction_equilibrium',
        'files_sha256':hashes,'source_digest':digest(hashes),
        'dependencies':dependencies,'dependency_digest':digest(dependencies),
        'units':{'length':'mm','mass':'kg','moment':'kg*mm'}}


class EquilibriumSpace(Space):
    """Retain real upstream geometry; replace every impact shortcut at one gate."""
    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config or BalancedConfig()
        self.config.__post_init__()
        self.pending_id = None
        self.attempt = None
        self.outcome = None

    def drop_box(self, box_size, idx, flag, density, setting, **kwargs):
        if setting != 1 or type(setting) is not int or flag is not False:
            raise BalanceUnsupported('FORBIDDEN_KERNEL_PATH')
        if self.pending_id is None:
            raise BalanceUnsupported('MISSING_PENDING_ID')
        if len(self.boxes) >= self.upLetter.shape[0]:
            raise BalanceUnsupported('HOLDER_CAPACITY_EXCEEDED')
        return super().drop_box(box_size,idx,False,density,setting,**kwargs)

    def drop_box_virtual(self, *args, **kwargs):
        raise BalanceUnsupported('VIRTUAL_PATH_UNSUPPORTED')

    def check_box(self, max_h, box_now, setting, virtual=False):
        if virtual:
            raise BalanceUnsupported('VIRTUAL_PATH_UNSUPPORTED')
        if setting != 1 or type(setting) is not int:
            raise BalanceUnsupported('FORBIDDEN_KERNEL_PATH')
        self.attempt = box_now
        box_now.item_id = self.pending_id
        boxes = [*self.boxes,box_now]
        nodes = []
        contacts = []
        for box in boxes:
            hull = box.bottom_whole_contact_area
            nodes.append(Node(box.item_id,float(box.mass),tuple(float(v) for v in box.centre),
                tuple(tuple(float(v) for v in row) for row in hull) if hull is not None else None))
            if not box.bottom_edges:
                if abs(box.lz)>self.config.height_tolerance_mm:
                    raise BalanceUnsupported('UNSUPPORTED_FLOATING_BOX')
                contacts.append(Contact(box.item_id,None,(box.lx,box.ly,box.lx+box.x,box.ly+box.y)))
            for edge in box.bottom_edges:
                contacts.append(Contact(box.item_id,edge.box.item_id,tuple(edge.area)))
        self.outcome = solve_network(nodes,contacts,float(max(self.plain_size[:2])),self.config)
        return self.outcome['status']=='STABLE'


def assess_candidate(placed_state, candidate, config=None):
    """Assess exactly one candidate with a fresh v2 network, in commit order."""
    start = time.perf_counter()
    cfg = config if config is not None else BalancedConfig()
    if not isinstance(cfg,BalancedConfig):
        raise ValueError('EXPECTED_BALANCED_CONFIG')
    cfg.__post_init__()
    ident = algorithm_identity()
    shash = chash = None
    baseline = 'NOT_ASSESSED'; first_bad = None; delta = None; pose = None
    calls = 0; diagnostics = {}; stage = 'input'; baseline_network_digest = None

    def result(status, reason):
        def safe(v):
            if isinstance(v,float) and not math.isfinite(v): return repr(v)
            if isinstance(v,dict): return {k:safe(x) for k,x in v.items()}
            if isinstance(v,(tuple,list)): return [safe(x) for x in v]
            return v
        name = getattr(candidate,'item_id',None)
        return BalancedResult(status,reason,shash,chash,name if isinstance(name,str) else None,
            digest(asdict(cfg)),ident,baseline,first_bad,None,delta,pose,calls,safe(diagnostics),
            time.perf_counter()-start)

    try:
        placed_state.validate(); candidate.validate()
        if candidate.item_id in {b.item_id for b in placed_state.placed}:
            raise ValueError('DUPLICATE_ITEM_ID')
        shash = digest(asdict(placed_state)); chash = digest(asdict(candidate))
        space = EquilibriumSpace(*placed_state.container_mm,holder=len(placed_state.placed)+2,config=cfg)
        for index,box in enumerate((*placed_state.placed,candidate)):
            is_candidate = index==len(placed_state.placed)
            stage = 'candidate' if is_candidate else 'prefix'
            first_bad = None if is_candidate else box.item_id
            if is_candidate: baseline = 'STABLE'
            if is_candidate and space.outcome is not None:
                baseline_network_digest = digest(space.outcome)
            diagnostics = {'restoring_item_id':box.item_id,'baseline_network_digest':baseline_network_digest,
                           'evaluated_scope':'geometry_precheck'}
            geo = to_kernel(box,placed_state.container_mm)
            lx,ly,z = geo['corner_mm']; sx,sy,sz = geo['size_mm']
            if min(lx,ly,z)<0 or lx+sx>space.plain_size[0] or ly+sy>space.plain_size[1] or z+sz>space.height:
                if not is_candidate: baseline = 'UNASSESSABLE'
                return result('UNASSESSABLE','OUT_OF_BOUNDS' if is_candidate else 'BASELINE_OUT_OF_BOUNDS')
            height = float(space.interSect2D(np.array([-lx,-ly,lx+sx,ly+sy,0]))[0])
            if not math.isfinite(height): raise BalanceNumericalError('NONFINITE_DROP_HEIGHT')
            delta = height-z
            pose = {'item_id':box.item_id,'kernel_corner_mm':[lx,ly,height],
                'original_bottom_center_mm':list(box.bottom_center_mm),
                'oriented_size_mm':list(box.size_mm),'density_kg_mm3':geo['density_kg_mm3']}
            if abs(delta)>cfg.height_tolerance_mm:
                if not is_candidate: baseline = 'UNASSESSABLE'
                return result('UNASSESSABLE','POSE_HEIGHT_MISMATCH' if is_candidate else 'BASELINE_POSE_HEIGHT_MISMATCH')
            space.pending_id = box.item_id
            space.attempt = None
            calls += 1
            with np.errstate(divide='raise',invalid='raise',over='raise',under='ignore'):
                ok = space.drop_box(box.size_mm,(lx,ly),False,geo['density_kg_mm3'],cfg.setting)
            kb = space.attempt
            if kb is None: raise BalanceNumericalError('GEOMETRY_REJECTED_BEFORE_EQUILIBRIUM')
            if not np.isclose(kb.mass,box.mass_kg,atol=cfg.mass_atol_kg,rtol=cfg.mass_rtol):
                raise BalanceNumericalError('BOX_MASS_MISMATCH')
            for actual,expected in [(kb.centre,geo['center_mm']),(kb.vertex_low,[lx,ly,z]),
                                   (kb.vertex_high,[lx+sx,ly+sy,z+sz])]:
                if not np.allclose(actual,expected,atol=cfg.height_tolerance_mm,rtol=0):
                    raise BalanceNumericalError('BOX_POSE_MISMATCH')
            outcome = space.outcome
            diagnostics = outcome['diagnostics']
            diagnostics['kernel_geometry_calls'] = calls
            diagnostics['evaluated_scope'] = 'post_drop_network'
            diagnostics['baseline_network_digest'] = baseline_network_digest
            diagnostics['boxes'] = [dict(item_id=b.item_id,mass_kg=float(b.mass),
                center_mm=b.centre.tolist(),corner_mm=b.vertex_low.tolist(),vertex_high_mm=b.vertex_high.tolist())
                for b in (space.boxes if ok else [*space.boxes,kb])]
            if not ok:
                if is_candidate: return result(outcome['status'],outcome['reason_code'])
                baseline = outcome['status']
                if baseline=='UNSTABLE': return result('UNASSESSABLE','BASELINE_UNSTABLE')
                return result(baseline,'BASELINE_'+outcome['reason_code'])
        first_bad = None
        return result('STABLE','CONTACT_NETWORK_BALANCED')
    except BalanceUnsupported as exc:
        if stage=='prefix': baseline = 'UNASSESSABLE'
        diagnostics = {**diagnostics,'stage':stage,'detail':str(exc)}
        return result('UNASSESSABLE',str(exc))
    except Exception as exc:
        if stage=='prefix': baseline = 'ERROR'
        diagnostics = {**diagnostics,**getattr(exc,'diagnostics',{}),'stage':stage,'exception_type':type(exc).__name__,'detail':str(exc)}
        if stage=='input' and isinstance(exc,(ValueError,TypeError,AttributeError,KeyError)):
            return result('UNASSESSABLE','INVALID_INPUT')
        return result('ERROR',str(exc) if isinstance(exc,BalanceNumericalError) else 'BALANCE_KERNEL_ERROR')
