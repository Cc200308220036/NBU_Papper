"""Read current durable status only; do not touch the live run directory."""
from pathlib import Path
import json
from collections import Counter
root=Path(__file__).resolve().parent
p=json.loads((root/'plan/plan.json').read_text());run=Path(p['run_location'])
if not run.exists():
    print('PRE_RUN_STATIC_VALIDATION; no new job directory yet')
else:
    states=Counter();categories=Counter();active=[]
    for j in p['jobs']:
        folder=run/'jobs'/j['job_id'];f=folder/'status.json'
        if not f.exists():states['INITIALIZING']+=1;continue
        s=json.loads(f.read_text());states[s['state']]+=1;categories[s['category']]+=1
        if s['state']=='RUNNING':
            cp=json.loads((folder/'checkpoint.json').read_text()) if (folder/'checkpoint.json').exists() else {}
            active.append({'job':j['job_id'],'task':j['task_id'],'method':j['method_id'],'decision':cp.get('decision'),'placed':cp.get('state',{}).get('placed_count'),'phase':cp.get('phase')})
    f=run/'request_ledger/requests.json';requests=json.loads(f.read_text())['requests'] if f.exists() else []
    result={'states':dict(states),'categories':dict(categories),'active':active,'reservations':len(requests),
            'request_states':dict(Counter(r['state'] for r in requests)),
            'served_models':sorted({r['selection']['served_model'] for r in requests if r.get('selection') and r['selection'].get('served_model')})}
    if (run/'technical_failure.json').exists():result['technical_failure']=json.loads((run/'technical_failure.json').read_text())
    print(json.dumps(result,ensure_ascii=False))
