"""Offline multi-method process viewer; reads records without replay or model calls."""
from importlib.resources import files
import hashlib
import json
from pathlib import Path

from ..contracts import canonical, JevSelectError
from ..ledger import write


def build_process_viewer(episodes, output, *, source_root=None):
    from ..experiment import _new_output
    root=_new_output(output);root.mkdir(parents=True)
    data=[];hashes={}
    for ep in episodes:
        frames=[]
        for e in ep['events']:
            ctx=e.get('context') or {}
            selection=e.get('selection') or {}
            frames.append({'event':e['event'],'decision_id':e.get('decision_id'),
              'before':e['before'],'after':e['after'], 'selected':selection.get('selected_display_id'),
              'criteria':ctx.get('criteria',{}),'display_mapping':ctx.get('display_mapping',{}),
              'memories':ctx.get('model_state',{}).get('memories',[]),
              'retrieval':ctx.get('retrieval'),
              'memory_binding':{k:v for k,v in ctx.get('local_binding',{}).items() if k in
                  ('memory_snapshot_digest','query_digest','retrieval_digest','injected_text_digest')},
              'instances':(e.get('business_after') or {}).get('instances',[]),
              'reason':e.get('reason'),'error':e.get('error')})
        data.append({'job_id':ep['job_id'],'summary':ep['summary'],'frames':frames})
        if source_root:
            path=Path(source_root)/'episodes'/f"{ep['job_id']}.json"
            hashes[str(path.relative_to(source_root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    template=files(__package__).joinpath('process.html').read_text(encoding='utf-8')
    html=template.replace('/*__PROCESS_DATA__*/',canonical(data).replace('<','\\u003c'))
    (root/'index.html').write_text(html,encoding='utf-8')
    write(root/'source_hashes.json',hashes)
    receipt={'status':'PASS','version':'jev_process_viewer_v1','jobs':len(data),
             'frames':sum(len(e['frames']) for e in data),'model_api_calls':0,'new_environment_steps':0,
             'html_sha256':hashlib.sha256(html.encode()).hexdigest()}
    write(root/'viewer_manifest.json',receipt)
    return receipt
