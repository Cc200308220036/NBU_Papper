"""Independent N1 runtime entry. Not registered in provider/episode/v14.

Only current-public snapshot bytes are accepted. Original source-lexeme generate
and adapt are never called. All geometric/physical generation uses one core.
"""
import copy

from .generator import _generation_core
from .contracts import digest
from ...jev_select.geometry_runtime_input import validate_runtime_snapshot_v1, runtime_config
from ...jev_select.geometry_runtime_contracts import encode, GeometryError


def generate_runtime_snapshot_v1(raw, *, native_snapshot_raw, binding, identities,
                                 config=None):
    config = runtime_config() if config is None else config
    def adapt_runtime(geometry_raw):
        v = validate_runtime_snapshot_v1(native_snapshot_raw, geometry_raw, binding,
                                         identities=identities, config=config)
        return v['exact'], v['physical'], v['geometry_state'], v['geometry_bytes'], digest(binding)
    result = _generation_core(raw, adapt_input=adapt_runtime,
                              identity_namespace='runtime_snapshot_v1')
    audit = result['audit']
    # Preserve even failed bindings on the audit side, never as request facts.
    audit.pop('semantic_digest')
    try:
        encode(binding)
        config_digest = digest(config)
        saved_binding = copy.deepcopy(binding)
    except (GeometryError, ValueError, TypeError):
        # Invalid caller records must not introduce NaN/bytes into error JSON.
        saved_binding = None
        config_digest = None
    audit.update(binding=saved_binding, source_contract='runtime_snapshot_v1',
                 profile='geometry_runtime_shortest_decimal_v1', runtime_config_digest=config_digest)
    audit['semantic_digest'] = digest(audit)
    return result
