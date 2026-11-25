"""GP6 formal single-step execution v1; authorization required, no retry/resume."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from . import instruction_probe as probe
from .contracts import DecisionContext, digest
from .ledger import exclusive, read, write
from .selector import parse_response
from .transport import JevTransport

PREP_DIGEST = '28fecc5cc49ba2f0e57e9270ba6f7467808233987015596849a45a6e798046af'
PACKAGE = Path('semantic_pallet_planner/outputs/GP6_INSTRUCTION_PROBE_EXEC_PREP_20261125_01')
RUN = Path('semantic_pallet_planner/outputs/GP6_INSTRUCTION_PROBE_EXEC_RUN_20261125_01')
MODEL = 'jev-1.14.0'
ENDPOINT = 'https://api.typesafe.ai/v1/systemone'

def require(ok, message):
    if not ok: raise ValueError(message)

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def frozen_files():
    files = [probe.OUTPUT/'plan.json', *sorted((probe.OUTPUT/'requests').glob('*.json')), *sorted((probe.OUTPUT/'contexts').glob('*.json'))]
    source = Path(__file__).resolve().parent.relative_to(Path.cwd().resolve())
    files += sorted(p for p in source.rglob('*') if p.suffix in ('.py','.json') and '__pycache__' not in p.parts)
    return {str(p):sha(p) for p in files}

def verify_prepared():
    prepared = read(probe.OUTPUT/'plan.json')
    require(digest(prepared)==PREP_DIGEST, 'prepared_plan_changed')
    transport = JevTransport(probe.load_config())
    expected=[]
    contexts,bodies={},{}
    for i, order in enumerate(probe.ORDERS):
        state=f'G01_D{i:04d}'
        context=read(probe.OUTPUT/'contexts'/f'{state}.json')
        contexts[state]=context
        info=prepared['states'][state]
        require(digest(context)==info['context_digest'], 'context_changed')
        require(digest(context['criteria'])==info['criteria_digest'] and digest(context['display_mapping'])==info['mapping_digest'], 'candidate_mapping_changed')
        require(probe.edges(context)==info['groups'], 'edge_groups_changed')
        for condition in ('original','left','right'):
            meta=info['requests'][condition]
            path=probe.OUTPUT/meta['path']
            require(sha(path)==meta['sha256'], 'body_changed')
            body=read(path)
            wanted=copy.deepcopy(context['request_body'])
            if condition!='original': wanted['questions']['next_action']['instructions']+='\n'+probe.TEXT[condition]
            require(body==wanted and transport.encode(body)==path.read_bytes(), 'body_or_serialization_changed')
            require(body['model']==MODEL, 'model_changed')
            bodies[(state,condition)]=body
        for rnd,sequence in enumerate((order,tuple(reversed(order))),1):
            for condition in sequence:
                expected.append((f'S{len(expected)+1:02d}',state,rnd,condition))
    require([(s['slot_id'],s['state'],s['round'],s['condition']) for s in prepared['slots']]==expected, 'slot_order_changed')
    require(len(expected)==18 and prepared['max_send_reservations']==18 and prepared['model']==MODEL and prepared['endpoint']==ENDPOINT, 'matrix_or_endpoint_changed')
    return prepared,contexts,bodies

def prepare(package=PACKAGE):
    require(not package.exists(), 'package_exists')
    prepared,_,_=verify_prepared()
    plan={'version':'gp6_instruction_execution_plan_v1','status':'PENDING_AUTHORIZATION','prepared_plan_digest':digest(prepared),'model':MODEL,'endpoint':ENDPOINT,'max_reservations':18,'run_root':str(RUN),'slots':prepared['slots'],'frozen_files':frozen_files(),'transport_config':probe.load_config(),'response_config':probe.config()}
    write(package/'execution_plan.json',plan)
    auth={'version':'gp6_instruction_execution_authorization_v1','status':'PENDING','authorization_id':None,'approval_reference':None,'plan_digest':digest(plan),'model':MODEL,'endpoint':ENDPOINT,'max_reservations':18,'run_root':str(RUN)}
    write(package/'authorization.pending.json',auth)
    write(package/'summary.json',{'version':'gp6_instruction_execution_summary_v1','plan_digest':digest(plan),'prepared_plan_digest':PREP_DIGEST,'slots':18,'bodies':9,'contexts':3,'real_calls':0,'status':'PENDING_INDEPENDENT_QA_AND_AUTHORIZATION'})
    return plan

def preflight(plan):
    require(plan['version']=='gp6_instruction_execution_plan_v1' and plan['status']=='PENDING_AUTHORIZATION','invalid_plan')
    require(plan['model']==MODEL and plan['endpoint']==ENDPOINT and plan['max_reservations']==18, 'execution_contract_changed')
    require(plan['run_root']==str(RUN), 'run_root_changed')
    require(plan['frozen_files']==frozen_files(), 'frozen_files_changed')
    require(plan['transport_config']==probe.load_config() and plan['response_config']==probe.config(), 'transport_config_changed')
    prepared,contexts,bodies=verify_prepared()
    require(plan['prepared_plan_digest']==PREP_DIGEST and plan['slots']==prepared['slots'], 'execution_slots_changed')
    return prepared,contexts,bodies

def validate_authorization(plan,auth):
    require(auth.get('version')=='gp6_instruction_execution_authorization_v1' and auth.get('status')=='AUTHORIZED', 'missing_authorization')
    require(isinstance(auth.get('authorization_id'),str) and bool(auth['authorization_id'].strip()) and isinstance(auth.get('approval_reference'),str) and bool(auth['approval_reference'].strip()), 'missing_approval_reference')
    require(auth.get('plan_digest')==digest(plan), 'authorization_plan_mismatch')
    for key in ('model','endpoint','max_reservations','run_root'):
        require(auth.get(key)==plan[key], 'authorization_binding_mismatch')

def durable_write(path,value):
    write(path,value)
    fd=os.open(str(Path(path).parent),os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def execute(plan,auth,*,transport_factory=None):
    """Only CLI uses native transport. Tests supply a factory; same gates and ledger."""
    prepared,contexts,bodies=preflight(plan)
    validate_authorization(plan,auth)
    root=Path(plan['run_root'])
    root.mkdir(parents=True,exist_ok=True)
    with exclusive(root):
        require(not (root/'started.json').exists(), 'authorization_already_started')
        # Recheck under lock, before consuming authorization or constructing transport.
        preflight(plan)
        durable_write(root/'started.json',{'version':'gp6_instruction_execution_start_v1','plan_digest':digest(plan),'authorization':auth,'status':'CONSUMED_NO_RESUME'})
        rows=[{'slot_id':s['slot_id'],'status':'NOT_RUN'} for s in plan['slots']]
        ledger={'version':'gp6_instruction_execution_ledger_v1','plan_digest':digest(plan),'authorization_digest':digest(auth),'reservations':0,'network_attempts':0,'origin':None,'status':'STARTED','rows':rows,'service_cost_usd':'UNKNOWN'}
        def persist(): durable_write(root/'requests.json',ledger)
        persist()
        transport=transport_factory() if transport_factory else JevTransport(plan['transport_config'])
        require(transport.origin in ('jev','test_double'), 'invalid_transport_origin')
        ledger['origin']=transport.origin
        try:
            for slot,row in zip(plan['slots'],rows):
                # Validate again before each potential credential lookup/send.
                try:
                    preflight(plan)
                except Exception:
                    ledger['status']='STOPPED_INTEGRITY_ERROR';persist();break
                # Send the verified in-memory body; never read an unchecked replacement.
                require(ledger['reservations']<18, 'budget_exhausted')
                row.update(status='RESERVED',state=slot['state'],condition=slot['condition'],round=slot['round'],request_sha256=slot['request']['sha256'])
                ledger['reservations']+=1;persist()
                row['status']='SENDING';persist()
                try:
                    saved=transport.complete(copy.deepcopy(bodies[(slot['state'],slot['condition'])]))
                except BaseException:
                    row['status']='UNKNOWN_SEND';ledger['status']='STOPPED_UNKNOWN_SEND';persist();break
                row['transport']=saved
                row['status']='RESPONSE_SAVED'
                ledger['network_attempts']+=int(saved.get('network_attempted',False));persist()
                try:
                    selected=parse_response(DecisionContext.from_dict(contexts[slot['state']]),{'origin':transport.origin,'attempt_id':slot['slot_id'],'transport':saved},plan['response_config']).data
                except Exception:
                    row['status']='ERROR';row['error']='RESPONSE_PROCESSING_ERROR';ledger['status']='STOPPED_ERROR';persist();break
                row['selection']=selected
                row['status']='UNKNOWN_SEND' if selected['status']=='unknown_in_flight' else selected['status']
                row['label']=selected['selected_display_id']
                row['side']=probe.classify(prepared['states'][slot['state']]['groups'],row['label'])
                if row['label']:
                    row['action']=contexts[slot['state']]['criteria'][row['label']]
                    row['native_probability_mass']={side:sum(selected['probabilities'][label] for label in labels) for side,labels in prepared['states'][slot['state']]['groups'].items()}
                persist()
                if row['status']=='UNKNOWN_SEND': ledger['status']='STOPPED_UNKNOWN_SEND';break
            else: ledger['status']='FINISHED'
        finally:
            persist()
            durable_write(root/'statistics.json',probe.statistics(prepared,rows))
        return ledger

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','execute'])
    parser.add_argument('--plan',type=Path,default=PACKAGE/'execution_plan.json')
    parser.add_argument('--authorization',type=Path)
    args=parser.parse_args()
    if args.command=='prepare': prepare()
    else:
        require(args.authorization is not None, 'missing_authorization')
        execute(read(args.plan),read(args.authorization))

if __name__=='__main__': main()
