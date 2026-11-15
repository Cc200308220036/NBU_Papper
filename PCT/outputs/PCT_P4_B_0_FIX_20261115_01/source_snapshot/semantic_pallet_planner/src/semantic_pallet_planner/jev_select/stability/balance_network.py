"""Global contact-network vertical equilibrium, preserving PCT hull geometry.

The old recursive single/two/multisupport split is never called here. All
force variables and two horizontal moments are solved simultaneously.
"""
from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import linprog

from .balance_contracts import BalancedConfig
from .vendor.pct.convex_hull import point_in_polygen


class BalanceNumericalError(RuntimeError):
    def __init__(self, code, diagnostics=None):
        super().__init__(code)
        self.diagnostics = diagnostics or {}


class BalanceUnsupported(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    item_id: str
    mass_kg: float
    center_mm: tuple
    hull_mm: tuple | None = None


@dataclass(frozen=True)
class Contact:
    upper: str
    lower: str | None  # None denotes ground
    rectangle_mm: tuple  # xmin,ymin,xmax,ymax, positive area


def _finite(value):
    if not np.isfinite(value).all():
        raise BalanceNumericalError('NONFINITE_NETWORK')


def _checked_solution(result, a, b, bounds_upper, cfg, phases=()):
    vector = np.asarray(result.x, dtype=float)
    try:
        _finite(vector)
        if vector.shape != (a.shape[1],):
            raise BalanceNumericalError('INVALID_SOLVER_VECTOR')
        if np.any(vector < 0):
            raise BalanceNumericalError('NEGATIVE_REACTION')
        if np.any(vector > bounds_upper + cfg.scaled_residual_tolerance):
            raise BalanceNumericalError('REACTION_BOUND_VIOLATION')
        residual = a @ vector - b
        _finite(residual)
        if np.max(np.abs(residual), initial=0) > cfg.scaled_residual_tolerance:
            raise BalanceNumericalError('EQUALITY_RESIDUAL')
    except BalanceNumericalError as exc:
        exc.diagnostics.update(solver_phases=list(phases),
                               raw_solver_vector=vector.tolist(),
                               scaled_residual_tolerance=cfg.scaled_residual_tolerance)
        raise
    return vector


def _halfplanes(hull):
    points = np.asarray(hull, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        raise BalanceUnsupported('DEGENERATE_SUPPORT_HULL')
    _finite(points)
    area2 = np.dot(points[:, 0], np.roll(points[:, 1], -1)) - np.dot(points[:, 1], np.roll(points[:, 0], -1))
    if abs(area2) <= 1e-12:
        raise BalanceUnsupported('DEGENERATE_SUPPORT_HULL')
    orientation = 1 if area2 > 0 else -1
    result = []
    for p, q in zip(points, np.roll(points, -1, axis=0)):
        d = q-p
        length = np.linalg.norm(d)
        if length == 0:
            raise BalanceUnsupported('DUPLICATE_HULL_VERTEX')
        normal = orientation*np.array([d[1], -d[0]])/length
        # Reject a nonconvex hull rather than silently replacing it.
        if np.max((points-p)@normal) > 1e-6:
            raise BalanceUnsupported('NONCONVEX_SUPPORT_HULL')
        result.append((p, normal))
    return result


def solve_network(nodes, contacts, length_scale_mm, cfg=None):
    """Canonical global solution, or an explicitly classified negative result.

    Nodes retain actual restoration order; contacts may be enumerated in any
    order. Diagnostics contain physical reactions for independent verification.
    """
    cfg = cfg or BalancedConfig()
    cfg.__post_init__()
    if not nodes or not math.isfinite(length_scale_mm) or length_scale_mm <= 0:
        raise BalanceUnsupported('INVALID_NETWORK_SCALE')
    by_id = {n.item_id: n for n in nodes}
    position = {n.item_id: i for i, n in enumerate(nodes)}
    if len(by_id) != len(nodes):
        raise BalanceUnsupported('DUPLICATE_NETWORK_NODE')
    for n in nodes:
        if len(n.center_mm) != 3 or not math.isfinite(n.mass_kg) or n.mass_kg <= 0:
            raise BalanceUnsupported('INVALID_NETWORK_NODE')
        _finite(n.center_mm)
    total = math.fsum(n.mass_kg for n in nodes)
    if not math.isfinite(total):
        raise BalanceNumericalError('NONFINITE_TOTAL_MASS')
    canonical = sorted(contacts, key=lambda c: (c.upper, c.lower or '', *c.rectangle_mm))
    seen = set()
    columns = []
    for c in canonical:
        key = (c.upper, c.lower)
        if key in seen:
            raise BalanceUnsupported('DUPLICATE_CONTACT')
        seen.add(key)
        if c.upper not in by_id or (c.lower is not None and c.lower not in by_id):
            raise BalanceUnsupported('UNKNOWN_CONTACT_NODE')
        if c.lower is not None and position[c.lower] >= position[c.upper]:
            raise BalanceUnsupported('NON_ACYCLIC_COMMIT_TOPOLOGY')
        if len(c.rectangle_mm) != 4:
            raise BalanceUnsupported('INVALID_CONTACT')
        _finite(c.rectangle_mm)
        x0, y0, x1, y1 = c.rectangle_mm
        if x1 <= x0 or y1 <= y0:
            raise BalanceUnsupported('DEGENERATE_CONTACT')
        for x, y in [(x0,y0),(x0,y1),(x1,y0),(x1,y1)]:
            columns.append((c.upper,c.lower,float(x),float(y)))
    if not columns or {c[0] for c in columns} != set(by_id):
        raise BalanceUnsupported('MISSING_SUPPORT_CONTACT')
    for n in nodes:
        outgoing = [c for c in canonical if c.upper == n.item_id]
        ground = [c for c in outgoing if c.lower is None]
        if ground and (len(outgoing) != 1 or n.hull_mm is not None):
            raise BalanceUnsupported('INVALID_GROUND_CONTACT')
        if not ground and n.hull_mm is None:
            raise BalanceUnsupported('MISSING_CONSERVATIVE_HULL')
    ordered = sorted(nodes, key=lambda n: n.item_id)
    row_index = {n.item_id: i for i,n in enumerate(ordered)}
    a = np.zeros((3*len(nodes),len(columns)))
    b = np.zeros(3*len(nodes))
    for n in ordered:
        b[3*row_index[n.item_id]] = n.mass_kg/total
    for j, (upper,lower,x,y) in enumerate(columns):
        for name,sign in [(upper,1),(lower,-1)]:
            if name is not None:
                node = by_id[name]
                i = 3*row_index[name]
                a[i:i+3,j] += sign*np.array([1,(x-node.center_mm[0])/length_scale_mm,
                                                            (y-node.center_mm[1])/length_scale_mm])
    hull_rows = []
    for n in ordered:
        if n.hull_mm is not None:
            for origin,normal in _halfplanes(n.hull_mm):
                row = np.zeros(len(columns))
                for j,(upper,_,x,y) in enumerate(columns):
                    if upper == n.item_id:
                        row[j] = np.dot(normal,np.array([x,y])-origin)/length_scale_mm
                hull_rows.append(row)
    g = np.array(hull_rows).reshape((-1,len(columns)))
    _finite(a); _finite(b); _finite(g)
    phases = []
    options = {'primal_feasibility_tolerance': cfg.solver_tolerance,
               'dual_feasibility_tolerance': cfg.solver_tolerance, 'presolve': cfg.presolve}

    def run(c, ae, be, gu=None, hu=None, bounds=None, phase=''):
        result = linprog(c, A_ub=gu, b_ub=hu, A_eq=ae, b_eq=be,
                         bounds=bounds, method=cfg.solver, options=options)
        phases.append({'phase': phase, 'status': int(result.status),
                       'message': str(result.message), 'iterations': int(result.nit) if result.nit is not None else None})
        if result.status not in (0,2):
            raise BalanceNumericalError('SOLVER_FAILURE:'+str(result.status),
                                        {'solver_phases':list(phases)})
        return result

    raw = run(np.zeros(len(columns)),a,b,bounds=(0,1),phase='physical_feasibility')
    common = {'solver_phases': phases, 'length_scale_mm': length_scale_mm,
              'mass_scale_kg': total, 'config': cfg.__dict__.copy(),
              'model': 'global_vertical_contact_vertices_with_retained_pct_hull'}
    if raw.status == 2:
        # Bounded separation certificate for A f=b, 0<=f<=1. Minimize
        # b*y+sum(w), subject to A.T*y+w>=0, |y|<=1, w>=0.
        neq, nv = a.shape
        objective = np.r_[b, np.ones(nv)]
        certificate = run(objective,None,None,np.c_[-a.T,-np.eye(nv)],np.zeros(nv),
                          [(-1,1)]*neq+[(0,None)]*nv,phase='separation_certificate')
        if certificate.status == 0:
            y = np.asarray(certificate.x[:neq]); _finite(y)
            projections = a.T@y
            lower_bound = float(np.minimum(projections,0).sum())
            rhs_dot = float(b@y)
            gap = lower_bound-rhs_dot
            _finite([lower_bound,rhs_dot,gap])
            common['infeasibility_certificate'] = dict(y=y.tolist(),
                column_projections=projections.tolist(), rhs_dot=rhs_dot,
                bounded_lower_bound=lower_bound, separation_gap=gap,
                verified=gap>cfg.certificate_gap)
            if gap > cfg.certificate_gap:
                return dict(status='UNSTABLE',reason_code='PHYSICAL_NETWORK_INFEASIBLE',diagnostics=common)
        return dict(status='UNASSESSABLE',reason_code='NETWORK_INFEASIBILITY_UNCERTIFIED',diagnostics=common)
    physical_vector = _checked_solution(raw,a,b,1,cfg,phases)
    common['physical_feasibility_witness'] = {
        'status':'FEASIBLE',
        'reactions':[dict(upper=upper,lower=lower,point_mm=[x,y],mass_kg=float(f*total))
                     for (upper,lower,x,y),f in zip(columns,physical_vector)],
        'scaled_equality_residual_max':float(np.max(np.abs(a@physical_vector-b),initial=0))}
    # Add a common interior slack variable; its optimum is frozen before
    # lexicographic force minimization. There is no force renormalization.
    ae = np.c_[a,np.zeros(len(b))]
    gu = np.vstack([np.c_[g,np.ones(len(g))],
                    np.c_[-np.eye(len(columns)),np.ones(len(columns))]])
    hu = np.zeros(len(g)+len(columns))
    objective = np.r_[np.zeros(len(columns)),-1.]
    margin = run(objective,ae,b,gu,hu,(0,1),phase='max_network_interior')
    if margin.status == 2:
        return dict(status='UNASSESSABLE',reason_code='CONSERVATIVE_HULL_INFEASIBLE',diagnostics=common)
    _checked_solution(margin,ae,b,1,cfg,phases)
    slack = float(margin.x[-1])
    common['max_network_interior_slack_scaled'] = slack
    if slack <= cfg.strict_interior_slack:
        return dict(status='UNASSESSABLE',reason_code='NETWORK_INTERIOR_BOUNDARY',diagnostics=common)
    slack_row = np.r_[np.zeros(len(columns)),1.]
    ae = np.vstack([ae,slack_row]); be = np.r_[b,slack]
    vector = np.asarray(margin.x)
    for j in range(len(columns)):
        objective = np.zeros(len(columns)+1); objective[j] = 1
        selected = run(objective,ae,be,gu,hu,(0,1),phase='lex_force_'+str(j))
        if selected.status != 0:
            raise BalanceNumericalError('LEXICOGRAPHIC_INCONSISTENCY')
        vector = _checked_solution(selected,ae,be,1,cfg,phases)
        row = np.zeros(len(columns)+1); row[j] = 1
        ae = np.vstack([ae,row]); be = np.r_[be,vector[j]]
    if gu is not None and np.max(gu@vector-hu,initial=0) > cfg.scaled_residual_tolerance:
        raise BalanceNumericalError('HULL_INEQUALITY_RESIDUAL')
    forces = vector[:-1]*total
    _finite(forces)
    if np.any(forces < 0):
        raise BalanceNumericalError('NEGATIVE_REACTION')
    reactions = [dict(upper=upper,lower=lower,point_mm=[x,y],mass_kg=float(mass))
                 for (upper,lower,x,y),mass in zip(columns,forces)]
    node_rows = []
    for n in ordered:
        outgoing = [r for r in reactions if r['upper']==n.item_id]
        incoming = [r for r in reactions if r['lower']==n.item_id]
        load = math.fsum(r['mass_kg'] for r in incoming)
        mass_res = math.fsum(r['mass_kg'] for r in outgoing)-n.mass_kg-load
        moment_res = [math.fsum(r['mass_kg']*(r['point_mm'][d]-n.center_mm[d]) for r in outgoing)
                      -math.fsum(r['mass_kg']*(r['point_mm'][d]-n.center_mm[d]) for r in incoming) for d in (0,1)]
        mass_tol = cfg.mass_atol_kg+cfg.mass_rtol*(n.mass_kg+load)
        moment_tol = cfg.moment_atol_kg_mm+cfg.moment_rtol*(n.mass_kg+load)*length_scale_mm
        if abs(mass_res)>mass_tol or max(abs(v) for v in moment_res)>moment_tol:
            raise BalanceNumericalError('PHYSICAL_NODE_RESIDUAL')
        center = [(n.mass_kg*n.center_mm[d]+math.fsum(r['mass_kg']*r['point_mm'][d] for r in incoming))/(n.mass_kg+load) for d in (0,1)]
        if n.hull_mm is not None and not point_in_polygen(np.array(center),np.asarray(n.hull_mm)):
            return dict(status='UNASSESSABLE',reason_code='CONSERVATIVE_HULL_BOUNDARY',diagnostics=common)
        node_rows.append(dict(item_id=n.item_id,own_mass_kg=n.mass_kg,
            own_center_mm=list(n.center_mm),incoming_mass_kg=load,
            outgoing_mass_kg=math.fsum(r['mass_kg'] for r in outgoing),
            equivalent_mass_kg=n.mass_kg+load,equivalent_center_xy_mm=center,
            mass_residual_kg=mass_res,moment_residual_kg_mm=moment_res,
            mass_tolerance_kg=mass_tol,moment_tolerance_kg_mm=moment_tol,
            retained_support_hull_mm=n.hull_mm))
    ground = [r for r in reactions if r['lower'] is None]
    ground_mass = math.fsum(r['mass_kg'] for r in ground)
    global_mass_res = ground_mass-total
    # About origin in physical mm, with math.fsum to avoid gratuitous cancellation.
    global_moment_res = [math.fsum(r['mass_kg']*r['point_mm'][d] for r in ground)
                        -math.fsum(n.mass_kg*n.center_mm[d] for n in nodes) for d in (0,1)]
    if abs(global_mass_res)>cfg.mass_atol_kg+cfg.mass_rtol*total or max(abs(v) for v in global_moment_res)>cfg.moment_atol_kg_mm+cfg.moment_rtol*total*length_scale_mm:
        raise BalanceNumericalError('GLOBAL_PHYSICAL_RESIDUAL')
    common.update(reactions=reactions,nodes=node_rows,input_total_mass_kg=total,
        ground_mass_kg=ground_mass,global_mass_residual_kg=global_mass_res,
        global_moment_residual_kg_mm=global_moment_res,
        scaled_equality_residual_max=float(np.max(np.abs(a@vector[:-1]-b),initial=0)),
        minimum_reaction_kg=float(np.min(forces)),
        global_conservation_checked=True,restored_order=[n.item_id for n in nodes])
    return dict(status='STABLE',reason_code='CONTACT_NETWORK_BALANCED',diagnostics=common)
