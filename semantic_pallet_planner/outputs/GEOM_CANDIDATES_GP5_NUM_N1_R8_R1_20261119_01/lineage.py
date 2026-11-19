"""Read-only, namespaced historical/current identity verification."""
import hashlib,json,subprocess
from pathlib import Path,PurePosixPath
SOURCE='8a860eea3ec22f8805eb6767660301acfd526653f566b1b1bd3e42b4af53578f'
LEGACY_PREFIX='/home/cyw/NBU_Papper/'
SRC='semantic_pallet_planner/src/semantic_pallet_planner/'
def read(p):return json.loads(Path(p).read_bytes())
def sha(raw):return hashlib.sha256(raw).hexdigest()
def relative(value):
    if value.startswith(LEGACY_PREFIX):value=value[len(LEGACY_PREFIX):]
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not p.parts:raise ValueError('UNSAFE_REPOSITORY_PATH')
    return str(p)
def member_bytes(row):
    p=relative(row['path'])
    if p!=row['path']:raise ValueError('MANIFEST_REQUIRES_RELATIVE_PATH')
    if row['kind']=='git':
        rev=row['revision']
        if len(rev)!=40 or any(c not in '0123456789abcdef' for c in rev):raise ValueError('UNPINNED_REVISION')
        return subprocess.check_output(['git','show',rev+':'+p])
    if row['kind']!='archive':raise ValueError('UNKNOWN_MEMBER_KIND')
    return Path(p).read_bytes()
def verify_rows(rows):
    for row in rows:
        if sha(member_bytes(row))!=row['sha256']:raise ValueError('LINEAGE_MEMBER_DRIFT:'+row['path'])
def current_source():
    root=Path(SRC)
    return {str(p.relative_to(root)):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(root).parts)}
def verify_freeze(inputs):
    f=read(Path(inputs)/'frozen_identity.json')
    verify_rows(f['historical_members']);verify_rows(f['current_members'])
    from semantic_pallet_planner.jev_select.contracts import digest
    current=current_source()
    if len(current)!=591 or current!=read(Path(inputs)/'source_manifest.json')['files'] or digest(current)!=SOURCE:raise ValueError('CURRENT_SOURCE_DRIFT')
    from semantic_pallet_planner.jev_select import geometry_order_execution as order
    mon=read(Path(inputs)/'monitor_snapshot.json');order.validate_monitor_snapshot(mon)
    plan=read(Path(inputs)/'plan.json');adm=read(Path(inputs)/'admission.json');configs=read(Path(inputs)/'configs.json')
    for job in plan['jobs']:
        if order.load_order_config(plan,job['job_id'],monitor_snapshot=mon,admission=adm)!=configs[job['job_id']]:raise ValueError('CURRENT_CONFIG_DRIFT')
