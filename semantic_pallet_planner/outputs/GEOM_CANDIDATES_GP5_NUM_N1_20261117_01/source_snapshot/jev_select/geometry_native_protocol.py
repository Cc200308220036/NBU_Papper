"""v17 protocol identity helpers; shared order engine and gates stay authoritative."""
from pathlib import Path
from .contracts import digest,JevSelectError
from .packaging_versions import GEOMETRY_NATIVE_VERSION,GEOMETRY_NATIVE_POLICY,GEOMETRY_NATIVE_BRIDGE

NAMES={name:name.rsplit('_v',1)[0]+'_v'+str(int(name.rsplit('_v',1)[1])+1) for name in (
    'geometry_order_plan_v1','geometry_order_execution_v1','geometry_order_durable_decision_v1',
    'geometry_order_metrics_v1','geometry_order_run_v1','geometry_order_accounting_v1',
    'geometry_development_binding_v1','geometry_kernel_launch_v1','geometry_order_admission_v1',
    'geometry_scope_authorization_v1','geometry_scope_review_v1','geometry_real_kernel_receipt_v2',
    'geometry_kernel_completion_review_v1','geometry_kernel_required_coverage_v1')}

def is_native(value):
    return value.get('version') in (GEOMETRY_NATIVE_VERSION,'geometry_order_plan_v2') or value.get('runtime_version')==GEOMETRY_NATIVE_VERSION

def wire(value,name):return NAMES[name] if is_native(value) else name

def policy_digest():
    return digest({'policy':GEOMETRY_NATIVE_POLICY,'bridge':GEOMETRY_NATIVE_BRIDGE,'source_sha256':digest({p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(__file__).with_name('geometry_native_shape_bridge.py'))})})

def config_fields():
    return {'publication_policy':GEOMETRY_NATIVE_POLICY,'native_shape_bridge':GEOMETRY_NATIVE_BRIDGE,'publication_policy_digest':policy_digest()}

def identity_fields(value):
    return {'runtime_version':GEOMETRY_NATIVE_VERSION,'publication_policy_digest':policy_digest()} if is_native(value) else {}
