"""Axis-aligned conversion; no signed-yaw transform or capacity accounting."""
from .contracts import BoxInput, PlacedState, finite


def to_kernel(box, container_mm):
    box.validate()
    x, y, z = box.bottom_center_mm
    sx, sy, sz = box.size_mm
    lx = x + container_mm[0]/2 - sx/2
    ly = y + container_mm[1]/2 - sy/2
    density = box.mass_kg/(sx*sy*sz)
    values = (lx, ly, z, density, sx*sy*sz)
    if not finite(values) or density <= 0:
        raise ValueError('UNREPRESENTABLE_GEOMETRY_OR_DENSITY')
    return {'corner_mm': (lx, ly, z), 'size_mm': box.size_mm,
            'center_mm': (x+container_mm[0]/2, y+container_mm[1]/2, z+sz/2),
            'density_kg_mm3': density}


def from_corner(corner, size, container_mm):
    return (corner[0]-container_mm[0]/2+size[0]/2,
            corner[1]-container_mm[1]/2+size[1]/2, corner[2])


def box_from_runtime(obj):
    """Explicit bridge from existing physical object; never infer mass or sort."""
    dims = obj['dimensions_mm']; pose = obj['pose']
    box = BoxInput(obj['item_id'], tuple(dims[k] for k in ('length','width','height')),
                   obj['mass_kg'], tuple(pose[k] for k in ('x_mm','y_mm','z_base_mm')), pose['yaw_deg'])
    box.validate()
    if 'oriented_size_mm' in obj and tuple(obj['oriented_size_mm']) != box.size_mm:
        raise ValueError('ORIENTED_SIZE_MISMATCH')
    return box


def state_from_runtime(state):
    c = state['container']
    return PlacedState(tuple(c[k] for k in ('length_mm','width_mm','max_height_mm')),
                       tuple(box_from_runtime(o) for o in state['placed_items']))
