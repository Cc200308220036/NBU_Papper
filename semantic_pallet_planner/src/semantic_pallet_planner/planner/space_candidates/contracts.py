"""GP1 exact geometry only: no candidate, physical oracle or runtime imports.

Input is a closed geometry-only JSON byte envelope, never a checkpoint.
All algorithm coordinates are Fractions parsed from original decimal lexemes.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
import hashlib
import json

VERSION = 'geometry_space_index_v1'
ALGORITHM = 'ems_surface_geometry_v1'
INPUT_VERSION = 'geometry_space_input_v1'
DEFAULT_LIMITS = {
    'active_spaces': 4096,
    'space_containment_comparisons': 2000000,
    'surface_event_cells': 16384,
    'surface_expansion_cell_checks': 2000000,
    # Reserved for GP2; no points are generated or counted in GP1.
    'raw_point_attempts_per_item': 32768,
}


class GeometryError(ValueError):
    def __init__(self, code, detail=''):
        self.code, self.detail = code, detail
        super().__init__(code + (': ' + detail if detail else ''))


def require(condition, detail):
    if not condition:
        raise GeometryError('INVALID_GEOMETRY_INPUT', detail)


def number(value):
    # A float has already lost its source lexeme; explicitly refuse that bridge.
    require(type(value) in (int, Decimal, Fraction), 'exact numeric value required')
    if isinstance(value, Decimal):
        require(value.is_finite(), 'finite decimal required')
    return Fraction(value)


def text(value):
    """Exact finite decimal without Decimal context rounding or negative zero."""
    value = number(value)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        fives += 1
        denominator //= 5
    require(denominator == 1, 'non-terminating decimal cannot be serialized')
    scale = max(twos, fives)
    numerator = value.numerator * 2 ** (scale-twos) * 5 ** (scale-fives)
    sign = '-' if numerator < 0 else ''
    digits = str(abs(numerator)).zfill(scale+1)
    result = digits if scale == 0 else (digits[:-scale] + '.' + digits[-scale:]).rstrip('0').rstrip('.')
    return sign + result if numerator else '0'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, order=True)
class AABB:
    # xmin,ymin,zmin,xmax,ymax,zmax (NOT the oracle's interleaved order).
    bounds: tuple

    def __post_init__(self):
        require(len(self.bounds) == 6, 'six bounds required')
        object.__setattr__(self, 'bounds', tuple(number(v) for v in self.bounds))
        require(all(self.bounds[d] < self.bounds[d+3] for d in range(3)), 'positive box required')

    def contains(self, other):
        return all(self.bounds[d] <= other.bounds[d] and other.bounds[d+3] <= self.bounds[d+3]
                   for d in range(3))

    def intersects(self, other):
        return all(max(self.bounds[d], other.bounds[d]) < min(self.bounds[d+3], other.bounds[d+3])
                   for d in range(3))

    def to_list(self):
        return [text(v) for v in self.bounds]


@dataclass(frozen=True)
class GeometryState:
    container: AABB
    placed: tuple  # sorted (AABB, item_id); immutable private geometric projection

    def semantic(self):
        return {'container': self.container.to_list(),
                'placed': [{'item_id': name, 'bounds': box.to_list()} for box, name in self.placed]}


def parse_input(raw):
    require(type(raw) is bytes, 'JSON bytes required, not a float mapping')
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'duplicate JSON key: ' + k)
            result[k] = v
        return result
    def invalid_constant(value):
        raise GeometryError('INVALID_GEOMETRY_INPUT', 'nonfinite JSON: ' + value)
    try:
        value = json.loads(raw, parse_float=Decimal, object_pairs_hook=pairs,
                           parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, GeometryError):
            raise
        raise GeometryError('INVALID_GEOMETRY_INPUT', 'invalid JSON') from exc
    def closed(obj, keys):
        require(type(obj) is dict and set(obj) == set(keys), 'closed object fields: ' + ','.join(keys))
    closed(value, ('version', 'container', 'placed_items'))
    require(value['version'] == INPUT_VERSION, 'unregistered geometry input')
    c = value['container']
    closed(c, ('length_mm', 'width_mm', 'max_height_mm'))
    l, w, h = (number(c[k]) for k in ('length_mm','width_mm','max_height_mm'))
    require(min(l, w, h) > 0, 'positive container dimensions')
    container = AABB((-l/2, -w/2, Fraction(0), l/2, w/2, h))
    require(type(value['placed_items']) is list, 'placed_items list required')
    boxes, names = [], set()
    for obj in value['placed_items']:
        closed(obj, ('item_id','pose','oriented_size_mm'))
        name = obj['item_id']
        require(type(name) is str and bool(name) and name not in names, 'unique nonempty item ID')
        names.add(name)
        pose = obj['pose']
        closed(pose, ('x_mm','y_mm','z_base_mm','yaw_deg'))
        require(type(pose['yaw_deg']) is int and pose['yaw_deg'] in (0,90), 'yaw must be 0/90')
        size = obj['oriented_size_mm']
        require(type(size) is list and len(size) == 3, 'three oriented dimensions')
        sx, sy, sz = (number(v) for v in size)
        require(min(sx, sy, sz) > 0, 'positive oriented dimensions')
        x, y, z = (number(pose[k]) for k in ('x_mm','y_mm','z_base_mm'))
        box = AABB((x-sx/2,y-sy/2,z,x+sx/2,y+sy/2,z+sz))
        require(container.contains(box), 'placed box outside container')
        boxes.append((box, name))
    boxes.sort()
    for i, (box, _) in enumerate(boxes):
        require(not any(box.intersects(other) for other, _ in boxes[:i]), 'placed positive-volume overlap')
    return GeometryState(container, tuple(boxes))


@dataclass
class _Record:
    box: AABB
    sources: set = field(default_factory=set)
    references: int = 0


class Budget:
    """One state-wide arena. Equal boundaries share one record, not copies.

    Lists/queues hold references; peak counts actual owned space records,
    including current parents and all retained/new intermediate children.
    A reduced-limit instance is only used by explicitly marked test doubles.
    """
    def __init__(self, limits=None):
        self.limits = dict(DEFAULT_LIMITS if limits is None else limits)
        require(set(self.limits) == set(DEFAULT_LIMITS) and
                all(type(v) is int and v >= 0 for v in self.limits.values()), 'invalid budget limits')
        self.used = {k: 0 for k in DEFAULT_LIMITS if k != 'raw_point_attempts_per_item'}
        self.extra = {'aabb_checks': 0, 'height_occupancy_checks': 0, 'surface_seeds': 0,
                      'surface_zero_height_skips': 0, 'surface_proposals': 0,
                      'duplicate_space_references': 0}
        self.arena = {}

    def charge(self, key, amount=1):
        next_value = self.used[key] + amount
        if next_value > self.limits[key]:
            raise GeometryError('GEOMETRY_BUDGET_EXCEEDED', key + ': ' + str(next_value))
        self.used[key] = next_value

    def acquire(self, bounds, source):
        # Check before allocating a geometric space record, even transiently.
        bounds = tuple(bounds)
        record = self.arena.get(bounds)
        if record is None:
            count = len(self.arena) + 1
            if count > self.limits['active_spaces']:
                raise GeometryError('GEOMETRY_BUDGET_EXCEEDED', 'active_spaces: ' + str(count))
            record = _Record(AABB(bounds))
            self.arena[bounds] = record
            self.used['active_spaces'] = max(self.used['active_spaces'], count)
        else:
            self.extra['duplicate_space_references'] += 1
        record.sources.add(source)
        record.references += 1
        return record

    def release(self, record):
        record.references -= 1
        if record.references == 0:
            del self.arena[record.box.bounds]

    def contains(self, a, b):
        self.charge('space_containment_comparisons')
        return a.contains(b)

    def free(self, box, state):
        self.extra['aabb_checks'] += 1
        if not self.contains(state.container, box):
            return False
        for occupied, _ in state.placed:
            self.extra['aabb_checks'] += 1
            if box.intersects(occupied):
                return False
        return True

    def snapshot(self):
        return {'limits': dict(self.limits), 'used': dict(self.used), 'observed': dict(self.extra),
                'raw_point_attempts': 'NOT_RUN_GP2', 'wall_clock_cutoff': False}
