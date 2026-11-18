"""E2 public-only remote compilation and explicit frozen compile-only plans.

No live call is made by offline development. Reuses the audited HTTP transport
and write-ahead attempt ledger, with a new schema, prompt and top-label assets.
"""
import copy
import json
import os
import shutil
import time
from pathlib import Path
import yaml
from ...common import O4Error, canonical, digest, read, write, SCHEMAS, CATEGORIES, FIELDS
from ...remote.transport import ChatTransport, ModelConfig
from ...remote_v2.compiler import AttemptLedger
from .protocol import rebind, validate_response, validate_observation, response_for
from .visual import render, facts
from .visual_verify import verify as verify_image
from .reference import audit, compare
from .compiler import compile_policy

PROMPT_VERSION='o4_e2_compile_prompt_v1'


def prompt():
    return '''Compile explicit Chinese pallet business instructions into the closed JSON response schema below.
Return only JSON. Copy request_id, state_hash, observation_digest, instruction_digest from public_request.
All facts are exact and complete. Labels are on pos_z TOP and boxes remain upright; this is a fixed assumption, not a policy rule.
inside_region requires the ENTIRE bottom footprint inside public region_id, not just its center; xy projection at any height. Use spatial_eps_mm=1e-6. Multiple regions conjoin.
relative_position is a directed ALL-PAIRS rule on distinct objects matching subject and reference. Never compare an object to itself. Endpoints still in the buffer have no pallet pose; defer until both placed, preserving symbolic selectors for future arrivals.
Coordinates are pallet bottom center: +x right, -x left, +y back, -y front. left_of: A.x_max+min_gap_mm<=B.x_min+eps; right_of: A.x_min>=B.x_max+min_gap_mm-eps; front_of: A.y_max+min_gap_mm<=B.y_min+eps; behind: A.y_min>=B.y_max+min_gap_mm-eps. Full AABB separation, NOT center comparison. No separation requirement on the other horizontal axis or on z.
min_gap_mm must be finite nonnegative numeric millimeters; emit0 if the instruction omits a gap. Zero gap allows face contact unless forbidden_contact separately prohibits it. relative_position overrides must be empty; explicit selector exclusions express exceptions. Inverse direction with swapped endpoints is equivalent; changing only direction or only endpoints is not.
no_top_load means cumulative direct+indirect top load <=0kg; max_top_load uses constant_kg or the target's label limit. forbidden_contact is symmetric direct positive-area face contact, not point/edge contact.
Business rules never relax physics. Category, reinforcement, fragile and labels do not automatically imply a rule; follow the full instruction.
Keep attribute selectors symbolic for later arrivals; explicit object IDs must be currently observed. Never invent coordinates, regions, candidate answers or actions.
Selector depth <=4, rules <=32, numeric selector values are kg, weight_class is light/medium/heavy.
Smaller priority means higher priority. Explicit overrides only replace lower-priority load rules on matching objects. inside_region overrides must be empty; spatial exceptions use selector exclusions.
Forbidden contact exceptions use selectors. Other active load rules conjoin by minimum limit. New spatial rules always conjoin.
If repair_error is present, fix only the reported format/binding violations, using the same public input; no reference answer is supplied.
''' + '\nCargo enums (food=食品, glassware=玻璃制品, electronics=电子产品, household_cleaner=清洁用品, general=普通货物): '+canonical(CATEGORIES)+'\nFields: '+canonical(FIELDS)+'\nResponse schema:\n'+canonical(read(SCHEMAS/'o4_e2_response.schema.json'))


def parse_response(payload, req):
    try:
        if not isinstance(payload,dict) or 'error' in payload:raise O4Error('provider_error')
        choice=payload['choices'][0]
        if choice.get('finish_reason')!='stop':raise O4Error('invalid_ast','incomplete model response')
        value=json.loads(choice['message']['content'])
    except O4Error:raise
    except (KeyError,IndexError,TypeError,ValueError) as exc:
        raise O4Error('invalid_ast','$.response: closed JSON object required') from exc
    return validate_response(value,req)


class RemoteCompiler:
    def __init__(self, root, transport, budget):
        self.root=Path(root);self.transport=transport;self.ledger=AttemptLedger(self.root,budget);self.records=[]
        write(self.root/'audit/attempts.json',[])

    def compile(self, req, condition):
        validate_observation(req)
        if req['images'] or condition not in ('text','image'):raise O4Error('invalid_remote_source')
        identifier=f'E2C{len(self.records)+1:06d}'
        asset=render(req,self.root,f'public/images/{identifier}.png');verify_image(req,self.root,asset)
        attached=copy.deepcopy(req);attached['images']=[asset] if condition=='image' else [];attached=rebind(attached)
        envelope={'schema_version':'o4_e2_visual_input_v1','condition':condition,'public_request':attached,
                  'visual_facts':facts(req),'images':attached['images']}
        record={'compilation_id':identifier,'condition':condition,'source':req,'envelope':envelope,
                'prompt_version':PROMPT_VERSION,'prompt_digest':digest(prompt()),'test_double':self.transport.test_double,
                'attempts':[],'response':None,'first_valid':False,'repaired_valid':False,'status':'in_flight'}
        path=self.root/f'responses/{identifier}.json';write(path,record)
        diagnostic=None
        for index in range(2):
            try:
                body=self.transport.body(envelope,self.root,prompt(),diagnostic)
                attempt=self.ledger.start(identifier,digest(body),index==1)
            except O4Error as exc:
                record['status']=exc.code;break
            started=time.perf_counter();payload=raw_text=None;response=None
            try:
                output=self.transport.complete(body);payload=output['payload'];raw_text=output.get('raw_text')
                response=parse_response(payload,attached);status='valid';diagnostic=None
            except O4Error as exc:
                status=exc.code;diagnostic={'code':exc.code,'detail':str(exc),'repair_scope':'format/bindings only; no reference answer'}
            saved=self.ledger.finish(attempt,status=status,payload=payload,raw_text=raw_text,repair_diagnostic=diagnostic,
                                     usage=payload.get('usage') if isinstance(payload,dict) else None,cost=None,
                                     latency_s=time.perf_counter()-started)
            record['attempts'].append(saved);record['status']=status
            if response is not None:
                record.update(response=response,first_valid=index==0,repaired_valid=index==1)
                break
            if status not in ('invalid_ast','invalid_binding'):break
        write(path,record);self.records.append(copy.deepcopy(record))
        return record


def prepare_remote(development_plan, output, profile, model_config):
    from .experiment import validate_plan,new_output,seal,files
    plan,data,config=validate_plan(development_plan)
    if profile not in ('compile-smoke','fixed'):raise O4Error('invalid_profile')
    raw=yaml.safe_load(Path(model_config).read_text());model=ModelConfig(**raw);model.validate()
    selected=[data['gold'][i] for i in (0,3,4,7,8,11,12,15,16,19,21,23)] if profile=='compile-smoke' else [
        {'case_id':f"{p['pair_id']}_{i}",**v,'candidates':p['candidates']} for p in data['pairs'] for i,v in enumerate(p['variants'])]
    root=new_output(output,(development_plan,));write(root/'private/cases.json',selected)
    write(root/'model.snapshot.json',model.snapshot())
    write(root/'plan.json',{'version':'o4_e2_remote_compile_v1','profile':profile,'case_ids':[c['case_id'] for c in selected],
                           'planned_records':len(selected)*4,'maximum_api_attempts':len(selected)*4,
                           'source_files':files(Path(__file__).resolve().parents[3]),'development_plan':str(Path(development_plan).resolve())})
    shutil.copytree(Path(development_plan)/'code_snapshot',root/'code_snapshot')
    (root/'prompt.txt').write_text(prompt());seal(root)
    return {'status':'PASS','profile':profile,'planned_records':len(selected)*4,'maximum_api_attempts':len(selected)*4,'new_api_attempts':0}


def run_remote(plan_root, output, budget, remote=False):
    from .experiment import new_output,verify_seal,seal,files
    if not remote:raise O4Error('remote_explicit_flag_required')
    if type(budget) is not int or budget<0:raise O4Error('invalid_api_budget')
    plan_root=Path(plan_root).resolve();verify_seal(plan_root);plan=read(plan_root/'plan.json')
    if plan['version']!='o4_e2_remote_compile_v1' or files(Path(__file__).resolve().parents[3])!=plan['source_files'] or (plan_root/'prompt.txt').read_text()!=prompt():
        raise O4Error('code_snapshot_mismatch')
    cfg=ModelConfig(**read(plan_root/'model.snapshot.json'))
    if not os.environ.get(cfg.api_key_env):raise O4Error('missing_api_key')
    root=new_output(output,(plan_root,));compiler=RemoteCompiler(root,ChatTransport(cfg),budget)
    cases=read(plan_root/'private/cases.json');rows=[]
    if [c['case_id'] for c in cases]!=plan['case_ids'] or len(cases)*4!=plan['planned_records']:
        raise O4Error('invalid_remote_plan_jobs')
    for c in cases:
        for backend in ('public_parser','remote_text','remote_image','oracle_ast'):
            req=c['request'];record=None
            if backend=='public_parser':response=compile_policy(req);status='valid'
            elif backend=='oracle_ast':response=response_for(req,c['reference_policy']);status='valid'
            else:
                record=compiler.compile(req,'text' if backend=='remote_text' else 'image');response=record['response'];status=record['status']
            objects=req['placed_objects']+req['available_objects'];expected=audit(req,c['reference_policy'],c['candidates'])['allowed_ids']
            metrics={'semantic_equal':False,'allowed_set_equal':False,'valid_ast':response is not None}
            if response is not None:
                metrics.update(compare(response['policy_ast'],c['reference_policy'],objects))
                allowed=audit(req,response['policy_ast'],c['candidates'])['allowed_ids']
                metrics.update(allowed_set_equal=allowed==expected,false_allow_ids=sorted(set(allowed)-set(expected)),false_reject_ids=sorted(set(expected)-set(allowed)))
            rows.append({'case_id':c['case_id'],'backend':backend,'status':status,'response':response,'metrics':metrics,
                         'compilation_id':record['compilation_id'] if record else None})
    report={'scope':'O4_E2_REAL_COMPILE','status':'PASS' if all(r['response'] is not None for r in rows) else 'PARTIAL',
            'planned_records':plan['planned_records'],'recorded_records':len(rows),'real_api_attempts':len(compiler.ledger.rows),
            'profile':plan['profile'],'test_double':False,'real_online_status':'NOT_RUN','unseen_generalization':'NOT_MEASURED'}
    report['per_backend']={backend:{'planned':len(cases),'valid_ast':sum(r['response'] is not None for r in rows if r['backend']==backend),
                                   'semantic_equal':sum(r['metrics']['semantic_equal'] for r in rows if r['backend']==backend),
                                   'allowed_set_equal':sum(r['metrics']['allowed_set_equal'] for r in rows if r['backend']==backend)}
                           for backend in ('public_parser','remote_text','remote_image','oracle_ast')}
    report['first_valid']=sum(r['first_valid'] for r in compiler.records)
    report['repaired_valid']=sum(r['repaired_valid'] for r in compiler.records)
    write(root/'plan.json',plan);write(root/'model.snapshot.json',cfg.snapshot());write(root/'private/cases.json',cases)
    write(root/'metrics/records.json',rows);write(root/'acceptance_report.json',report);seal(root)
    return report
