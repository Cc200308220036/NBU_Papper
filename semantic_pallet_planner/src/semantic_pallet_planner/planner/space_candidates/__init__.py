"""Independent GP1 space index; not registered as an online candidate backend."""
import hashlib
from .contracts import ALGORITHM, VERSION, Budget, GeometryError, digest, parse_input
from .empty_spaces import empty_spaces
from .surface_spaces import surface_spaces


def build_space_index(raw):
    """Closed geometry JSON bytes -> complete spaces or atomic technical ERROR.

    No candidates, item placements, physical admission, LP or online routing.
    Default production budgets are fixed; reduced limits are test-only internals.
    """
    return _build_space_index(raw, Budget())


def _build_space_index(raw, budget):
    result = {'version': VERSION, 'algorithm': ALGORITHM, 'status': 'ERROR',
              'input_digest': None, 'config_digest': digest(budget.limits),
              'spaces': [], 'surface': None, 'error': None}
    try:
        state = parse_input(raw)
        result['input_digest'] = digest(state.semantic())
        ems = empty_spaces(state, budget)
        surface, audit = surface_spaces(state, budget)
        merged = {record.box.bounds: record for record in ems + surface}
        for bounds in sorted(merged):
            record = merged[bounds]
            if not budget.free(record.box, state):
                raise GeometryError('SPACE_GEOMETRY_INVARIANT_ERROR')
        # Only publish after every source and invariant has completed.
        result['spaces'] = [{'space_id': 'space_' + digest(record.box.to_list()),
                             'bounds_mm': record.box.to_list(), 'source_types': sorted(record.sources)}
                            for _, record in sorted(merged.items())]
        result['surface'] = audit
        result['status'] = 'OK' if result['spaces'] else 'OK_EMPTY'
    except GeometryError as exc:
        result.update(status='ERROR', spaces=[], surface=None,
                      error={'code': exc.code, 'detail': exc.detail})
    result['budget_usage'] = budget.snapshot()
    # Byte identity separate from normalized, sorted semantic input identity.
    result['source_bytes_sha256'] = hashlib.sha256(raw).hexdigest() if type(raw) is bytes else None
    result['semantic_digest'] = digest({k:v for k,v in result.items() if k != 'source_bytes_sha256'})
    return result
