"""Exact event surface, finite quadrant corner rule and two greedy axis orders."""
from .contracts import GeometryError, digest, text


def surface_spaces(state, budget):
    c = state.container.bounds
    xs = sorted({c[0], c[3]} | {b.bounds[d] for b, _ in state.placed for d in (0,3)})
    ys = sorted({c[1], c[4]} | {b.bounds[d] for b, _ in state.placed for d in (1,4)})
    nx, ny = len(xs)-1, len(ys)-1
    budget.charge('surface_event_cells', nx*ny)  # before grid allocation
    heights = []
    for i in range(nx):
        column = []
        for j in range(ny):
            h = c[2]
            for box, _ in state.placed:
                budget.extra['height_occupancy_checks'] += 1
                b = box.bounds
                if b[0] <= xs[i] and xs[i+1] <= b[3] and b[1] <= ys[j] and ys[j+1] <= b[4]:
                    h = max(h, b[5])
            column.append(h)
        heights.append(column)

    def different(i, j, h):
        return not (0 <= i < nx and 0 <= j < ny) or heights[i][j] != h

    def expand(i, j, h, axes):
        # Half-open cell rectangle [xlo,xhi) x [ylo,yhi).
        r = [i, j, i+1, j+1]
        for axis in axes:
            for direction in (-1, 1):
                while True:
                    edge = r[axis]-1 if direction == -1 else r[axis+2]
                    if not 0 <= edge < (nx if axis == 0 else ny):
                        break
                    strip = ((edge, q) for q in range(r[1],r[3])) if axis == 0 else ((q, edge) for q in range(r[0],r[2]))
                    accepted = True
                    for x, y in strip:
                        budget.charge('surface_expansion_cell_checks')
                        if heights[x][y] > h:
                            accepted = False
                            break
                    if not accepted:
                        break
                    r[axis if direction == -1 else axis+2] += direction
        return (xs[r[0]], ys[r[1]], h, xs[r[2]], ys[r[3]], c[5])

    spaces = {}
    seeds = []
    for vx in range(nx+1):
        for vy in range(ny+1):
            for dx in (-1,1):
                for dy in (-1,1):
                    i, j = (vx-1 if dx == -1 else vx), (vy-1 if dy == -1 else vy)
                    if not (0 <= i < nx and 0 <= j < ny):
                        continue
                    h = heights[i][j]
                    if not (different(i-dx, j, h) and different(i, j-dy, h)):
                        continue
                    budget.extra['surface_seeds'] += 1
                    seed = {'vertex_mm': [text(xs[vx]), text(ys[vy])], 'quadrant': [dx,dy],
                            'seed_z_mm': text(h), 'expansions': []}
                    seeds.append(seed)
                    if h == c[5]:
                        budget.extra['surface_zero_height_skips'] += 1
                        continue
                    for axes in ((0,1),(1,0)):
                        bounds = expand(i, j, h, axes)
                        record = budget.acquire(bounds, 'SURFACE_CORNER')
                        if not budget.free(record.box, state):
                            raise GeometryError('SURFACE_GEOMETRY_INVARIANT_ERROR')
                        budget.extra['surface_proposals'] += 1
                        # Audit uses boundary-derived ID, no additional space copy.
                        seed['expansions'].append({'axis_order': list(axes), 'space_id': 'space_' + digest(record.box.to_list())})
                        if bounds in spaces:
                            budget.release(record)
                        else:
                            spaces[bounds] = record
    return list(spaces.values()), {'x_events_mm': [text(x) for x in xs], 'y_events_mm': [text(y) for y in ys],
                                  'height_columns_mm': [[text(h) for h in column] for column in heights], 'seeds': seeds}
