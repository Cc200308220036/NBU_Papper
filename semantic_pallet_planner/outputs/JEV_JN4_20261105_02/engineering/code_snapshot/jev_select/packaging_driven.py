"""Central per-decision protocol versions; imports implementations lazily."""
VERSIONS={'jev_packaging_memory_orders_v9':'v9','jev_packaging_evaluation_v10':'v10'}
def is_driven(config):return config.get('version') in VERSIONS
def memory_interface(version):
    if version=='jev_packaging_memory_orders_v9':
        from . import packaging_pilot_memory
        return packaging_pilot_memory
    if version=='jev_packaging_evaluation_v10':
        from . import packaging_evaluation_memory
        return packaging_evaluation_memory
    raise ValueError('unregistered_per_decision_memory_protocol')
