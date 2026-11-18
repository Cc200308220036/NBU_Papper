"""Independent O2a artifact verifier: replay raw responses, prompts and frozen bindings."""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
from ..protocol import canonical_json
from ..vlm.pilot_protocol_v2 import parse_choice as parse_old, scan_public, SYSTEM_PROMPT as OLD_PROMPT
from ..vlm.protocol_o2a import ChoiceProtocolError
from .attribute_pilot_v2 import read_json, write_json, sha
from .protocol_o2a import inventory_digest, DEFAULT_V1


def verify(root: Path):
    root=root.resolve(); m=read_json(root/'manifest.json')
    data=read_json(root/'data/pilot_dataset.private.json')
    rows=read_json(root/'metrics/per_decision.json')
    rowmap={(r['request_id'],r['method']):r for r in rows}
    snapshot=root/'code_snapshot/semantic_pallet_planner/src/semantic_pallet_planner/vlm/protocol_o2a.py'
    tree=ast.parse(snapshot.read_text())
    constants={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            try:constants[node.targets[0].id]=ast.literal_eval(node.value)
            except (ValueError,TypeError):pass
    frozen_schema=constants['VERSION']; frozen_prompt=constants['SYSTEM_PROMPT']
    frozen_repair=constants['REPAIR_PROMPT']
    reason_limit=160 if frozen_schema.endswith('_1') else 3000
    def parse_frozen(raw,req):
        obj=json.loads(raw)
        fields={'schema_version','request_id','state_hash','policy_digest','action','display_label','reason'}
        if not isinstance(obj,dict) or set(obj)!=fields or obj['schema_version']!=frozen_schema:
            raise ValueError('response_schema')
        if any(obj[k]!=req[k] for k in ('request_id','state_hash','policy_digest')):
            raise ValueError('binding')
        if not isinstance(obj['reason'],str) or len(obj['reason'])>reason_limit:
            raise ValueError('reason')
        if obj['action']=='abstain' and obj['display_label'] is None:return obj
        if obj['action']!='select' or obj['display_label'] not in {c['display_label'] for c in req['candidates']}:
            raise ValueError('action_or_label')
        return obj
    failures=[]; checked=0; repairs=0; first_valid={'old_prompt':0,'new_prompt':0}
    if len(rowmap)!=len(rows) or len(data)*3!=len(rows): failures.append('record_cardinality')
    for item in data:
        req=item['public_request'];rid=req['request_id'];real_ids=item['mapping'].values()
        if scan_public(req,real_ids)['status']!='PASS':failures.append(rid+':public_leakage')
        if sha(root/'data/public_requests'/f'{rid}.json')!=sha(root/'selector_inputs/old_prompt'/rid/'public_request.json'):
            failures.append(rid+':public_request_changed')
        for arm in ('old_prompt','new_prompt'):
            checked+=1;folder=root/'selector_inputs'/arm/rid
            if not (folder/'attempts.json').is_file():failures.append(rid+':'+arm+':no_attempts');continue
            log=read_json(folder/'attempts.json');row=rowmap[(rid,arm)]
            prompt=read_json(folder/'prompt.json')
            expected_user=canonical_json(req)
            expected_system=OLD_PROMPT if arm=='old_prompt' else frozen_prompt
            if prompt['user_text']!=expected_user or prompt['system_prompt']!=expected_system:
                failures.append(rid+':'+arm+':prompt_mismatch')
            parser=parse_old if arm=='old_prompt' else parse_frozen
            attempts=[]
            for name in ('initial_response','repair_response'):
                file=folder/f'{name}.raw.json'
                if file.is_file():
                    raw=read_json(file)
                    try:choice=parser(raw['raw_text'],req)
                    except (ValueError,TypeError):choice=None
                    attempts.append((name,choice,raw))
            if not attempts or len(attempts)!=len(log['attempts']) or len(attempts)!=row['attempt_count']:
                failures.append(rid+':'+arm+':attempt_count')
                continue
            initial=attempts[0][1]
            if bool(initial)!=log['initial_valid'] or bool(initial)!=row['initial_api_valid']:
                failures.append(rid+':'+arm+':initial_valid')
            first_valid[arm]+=initial is not None
            final=attempts[-1][1]
            if bool(final)!=log['final_valid'] or bool(final)!=row['final_api_valid']:
                failures.append(rid+':'+arm+':final_valid')
            expected_status=final['action'] if final else 'invalid_response'
            if row['status']!=expected_status or row['display_label']!=(final['display_label'] if final else None):
                failures.append(rid+':'+arm+':final_choice')
            if len(attempts)>1:
                repairs+=1
                if arm!='new_prompt' or len(attempts)!=2 or initial is not None:
                    failures.append(rid+':'+arm+':unallowed_repair')
                else:
                    rp=read_json(folder/'repair_prompt.json')
                    error_code=log['attempts'][0]['error_code']
                    if rp['user_text']!=frozen_repair.format(error_code=error_code,request=canonical_json(req)) or rp['system_prompt']!=frozen_prompt or scan_public(req,real_ids)['status']!='PASS':
                        failures.append(rid+':'+arm+':repair_not_public_only')
            elif (folder/'repair_prompt.json').exists():
                failures.append(rid+':'+arm+':orphan_repair')
            if row['input_tokens']!=sum(a[2]['input_tokens'] or 0 for a in attempts):
                failures.append(rid+':'+arm+':tokens')
    source=read_json(root/'data/split_audit.json')
    if source['v2_source_order_overlap'] or source['test_source_order_overlap']:
        failures.append('split_leakage')
    for rel,h in m['data_sha256'].items():
        if sha(root/rel)!=h:failures.append('frozen_data:'+rel)
    for rel,h in m['source_sha256'].items():
        snapshot=root/'code_snapshot'/rel
        if not snapshot.exists() or sha(snapshot)!=h:failures.append('code_snapshot:'+rel)
    for path,before in ((Path(m['v1_directory']),m['v1_before']),
                        (Path(m['parent_v2_directory']),m['parent_v2_before'])):
        if inventory_digest(path)!=before:failures.append('historical_directory_changed:'+path.name)
    report={'status':'PASS' if not failures else 'FAIL','raw_model_requests_checked':checked,
            'first_response_valid':first_valid,'repair_calls':repairs,'failures':failures,
            'old_critical_human_double_review':'PENDING',
            'verifier_sha256':sha(Path(__file__))}
    write_json(root/'checks/independent_verification.json',report)
    return report


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True)
    args=ap.parse_args(argv);result=verify(Path(args.output))
    print(json.dumps(result,ensure_ascii=False))
    if result['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
