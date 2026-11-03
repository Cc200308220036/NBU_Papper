"""Create a single offline HTML file and verify original evidence remains untouched."""
import json,hashlib
from pathlib import Path
root=Path('semantic_pallet_planner/outputs/JEV_JN0_VISUAL_20261103_01');web=root/'web'
html=(web/'index.html').read_text();css=(web/'style.css').read_text();app=(web/'app.js').read_text();data=(web/'data.js').read_text()
assert '</script' not in app.lower()
html=html.replace('<link rel="stylesheet" href="style.css">','<style>'+css+'</style>')
html=html.replace('<script src="data.js"></script>','<script>'+data.replace('<','\\u003c')+'</script>')
html=html.replace('<script src="app.js"></script>','<script>'+app+'</script>')
(root/'JN0_interactive.html').write_text(html)
source=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02');frozen=json.loads((source/'delivery_manifest.json').read_text())['files_sha256']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert all(sha(source/n)==h for n,h in frozen.items())
receipt={'version':'jev_jn0_interactive_review_delivery_v1','status':'PASS','entry':'JN0_interactive.html','development_entry':'web/index.html',
 'source_delivery':str(source),'source_delivery_manifest_sha256':sha(source/'delivery_manifest.json'),
 'original_frozen_files_verified':len(frozen),'source_modified':False,'order_executions':0,'model_calls':0,'solver_calls':0,
 'jobs':8,'events':150,'monitored_actions':61,'stable_actions':59,'unassessable_actions':2,
 'independent_node_balances':263,'arithmetic_audit':'computation_audit.json','browser_qa':'qa/browser_acceptance.json',
 'hosting':'LOCAL_ONLY; user no-auto-commit/push preference preserved','external_dependencies':[],
 'limitations':['Static three-dimensional projection from saved poses; not a new physical simulation','Browser arithmetic is a check of saved reactions, not a new LP solve','No unstable examples observed in these eight runs; no invented unstable result','Two height-mismatch results have no final candidate reaction solution','Inventory includes future items only for post-hoc inspection, never a model input']}
(root/'handoff.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
manifest={p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p!=root/'delivery_manifest.json'}
(root/'delivery_manifest.json').write_text(json.dumps({'version':'jev_jn0_viewer_manifest_v1','files_sha256':manifest},ensure_ascii=False,indent=2)+'\n')
print('offline entry',root/'JN0_interactive.html','bytes',len(html.encode()),'files',len(manifest),'original evidence unchanged')
