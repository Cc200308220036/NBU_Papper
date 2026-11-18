"""Deterministic six full-cross-section slabs. No physical admission rules."""
from collections import deque
from .contracts import GeometryError


def remove_redundancy(records, budget):
    """Consume owned references: deduplicate BEFORE directed containment tests."""
    unique = {}
    for record in records:
        bounds = record.box.bounds
        if bounds in unique:
            budget.release(record)
        else:
            unique[bounds] = record
    records.clear()
    ordered = [unique[k] for k in sorted(unique)]
    contained = []
    keep = []
    for i, record in enumerate(ordered):
        if any(budget.contains(other.box, record.box) for j, other in enumerate(ordered) if i != j):
            contained.append(record)
        else:
            keep.append(record)
    for record in contained:
        budget.release(record)
    return keep


def empty_spaces(state, budget):
    spaces = [budget.acquire(state.container.bounds, 'EMS_STYLE_3D')]
    for occupied, _ in state.placed:
        pending = deque(spaces)
        spaces.clear()  # transfer owned references, do not copy space records
        children = []
        while pending:
            record = pending.popleft()
            budget.extra['aabb_checks'] += 1
            if not record.box.intersects(occupied):
                children.append(record)
                continue
            e, b = record.box.bounds, occupied.bounds
            low = tuple(max(e[d], b[d]) for d in range(3))
            high = tuple(min(e[d+3], b[d+3]) for d in range(3))
            # Parent remains owned until ALL children have been allocated.
            for d in range(3):
                if e[d] < low[d]:
                    slab = list(e)
                    slab[d+3] = low[d]
                    children.append(budget.acquire(slab, 'EMS_STYLE_3D'))
                if high[d] < e[d+3]:
                    slab = list(e)
                    slab[d] = high[d]
                    children.append(budget.acquire(slab, 'EMS_STYLE_3D'))
            budget.release(record)
        spaces = remove_redundancy(children, budget)
    for record in spaces:
        if not budget.free(record.box, state):
            raise GeometryError('SPACE_GEOMETRY_INVARIANT_ERROR')
    return spaces
