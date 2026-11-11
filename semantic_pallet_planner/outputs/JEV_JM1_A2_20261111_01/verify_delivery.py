"""Read-only stdlib delivery check. No project imports or experiment dispatch."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dg(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def check(ok, detail):
    if not ok: raise AssertionError(detail)

manifest = read(OUT/'delivery_manifest.json')
for rel, expected in manifest['files_sha256'].items():
    check(sha(ROOT/rel)==expected, 'delivery bytes: '+rel)
inputs = read(OUT/'input_evidence_index.json')
for rel, expected in inputs['files_sha256'].items():
    check(sha(ROOT/rel)==expected, 'parent bytes: '+rel)
source = read(OUT/'source_identity.json')
for rel, expected in source['runtime_package_source_sha256'].items():
    check(sha(ROOT/rel)==expected,'runtime source: '+rel)
for filename,n in [('constructed_junit.xml',58),('public_regression_junit.xml',50)]:
    suites=ET.parse(OUT/filename).getroot().findall('.//testsuite')
    check(sum(int(s.attrib['tests']) for s in suites)==n,filename)
    check(all(int(s.attrib['errors'])==int(s.attrib['failures'])==0 for s in suites),filename)
roots=[]
for p in (OUT/'constructed_evidence').glob('*/a2'):
    # Tampered records are intentional negative fixtures; checked by pytest.
    if p.parent.name.startswith('test_identity_tamper'):continue
    if not (p/'episode.json').exists():continue
    roots.append(p)
    episode=read(p/'episode.json');counts=read(p/'counts.json');ex=read(p/'activation.json')
    check(read(p/'ledger/execution.json')==ex,'execution anchor')
    check(ex['binding_digest']==dg(ex['binding']),'binding identity')
    ledger=read(p/'ledger/requests.json')
    check(ledger['record_digest']==dg({k:v for k,v in ledger.items() if k!='record_digest'}),'ledger seal')
    for row in ledger['requests']:
        ctx=read(p/'ledger/contexts'/f'{row["decision_id"]}.json')
        check(row['context_digest']==dg(ctx) and row['body_digest']==dg(ctx['request_body']),'request identity')
        check(row['mapping_digest']==dg(ctx['display_mapping']),'mapping identity')
        reservation=read(p/'ledger/reservations'/f'{row["decision_id"]}.json')
        check(reservation['execution_digest']==dg(ex),'reservation execution identity')
        check(all(reservation[k]==row[k] for k in ('job_id','decision_id','body_digest','mapping_digest','context_digest')),'reservation identity')
        check(ctx['request_body']['state']['memories']==[],'memory leak')
        check(row['origin']=='test_double','not a fake origin')
        if row['transport'] is not None:check(row['transport_digest']==dg(row['transport']),'response identity')
        if row['selection'] is not None:check(row['selection_digest']==dg(row['selection']),'selection identity')
    events=[e for e in episode['events'] if e.get('selection')]
    check(counts['forced_actions']==sum(e['selection']['source']=='FORCED_FROM_FROZEN_POOL' for e in events)==1,'forced count')
    check(counts['constructed_requests']==sum(r['send_started'] for r in ledger['requests']),'fake request count')
    check(counts['real_model_calls']==0,'real calls')
    check(counts['singleton_actions']==sum(e['selection']['source']=='singleton' for e in events),'singleton count')
    check(counts['commits']==sum(e['event']=='PLACE' for e in events),'commit count')
    selected={};monitored={}
    for stage in sorted((p/'stages').glob('*.json')):
        cp=read(stage)
        check(cp['record_digest']==dg({k:v for k,v in cp.items() if k!='record_digest'}),'checkpoint seal')
        e=cp['pending_event']
        if e is None:continue
        did=e['decision_id']
        if cp['phase']=='SELECTED':
            check(e['monitor'] is None,'monitor before save');selected[did]=e['selection']
        if cp['phase']=='MONITORED':
            check(selected.get(did)==e['selection'],'unsaved choice monitored');monitored[did]=e['monitor']
        if cp['phase']=='COMMITTED':check(monitored[did]['status']=='STABLE','failure committed')
    for e in events:
        if e.get('monitor') and e['monitor']['status']!='STABLE':
            check(e['before']==e['after'] and e['action'] is None,'failure mutation')
check(len(roots)>=15,'missing constructed records')
report=ROOT/'docs/03_阶段产出分析/Jev/Jev_JM1-A2无经验后续路由独立账本与停止验收_20261111_01.md'
for link in re.findall(r'\]\(([^)]+)\)',report.read_text()):
    if '://' not in link:check((report.parent/link).exists(),'broken report link: '+link)
print(json.dumps({'status':'PASS','scope':'READ_ONLY_STDLIB_NO_PROJECT_IMPORTS','delivery_files':len(manifest['files_sha256']),
                  'input_files':len(inputs['files_sha256']),'constructed_execution_roots':len(roots)},ensure_ascii=False))
