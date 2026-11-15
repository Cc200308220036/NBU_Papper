"""P4-B-0 immutable formal descriptor and bounded campaign ledger.

The formal descriptor is separate from the permanently non-executable P4-A
plan. No public engine route is registered; launch cannot dispatch business work.
"""
import copy
from .contracts import digest, require
from .p4a import validate_plan
from .p4b_runtime import EXECUTION, RECOVERY, admit_business, attempt_denominator
from .p4b_storage import VERSION, UPDATE, seal


def descriptor(plan, catalog, *, source_identity, environment_identity):
    validate_plan('training',plan,catalog,plan['input_identity'],plan['build_spec'])
    require(bool(source_identity) and bool(environment_identity),'P4B_EXECUTOR_IDENTITY')
    return seal({'version':EXECUTION,'recovery':RECOVERY,'storage':VERSION,'update':UPDATE,
                 'parent_plan_digest':plan['plan_digest'],'models':copy.deepcopy(plan['models']),
                 'schedules':copy.deepcopy(plan['schedules']),'rules':copy.deepcopy(plan['rules']),
                 'source':source_identity,'environment':environment_identity,
                 'business_admission':'BLOCKED_PUBLIC_ROUTING_AND_INDEPENDENT_ACCEPTANCE',
                 'denominators':copy.deepcopy(plan['denominators'])})


class Campaign:
    def __init__(self,store,formal):
        require(formal['seal']==digest({k:v for k,v in formal.items() if k!='seal'}) and
                formal['version']==EXECUTION,'P4B_DESCRIPTOR')
        require(store.identity.get('formal_descriptor')==formal['seal'],'P4B_CAMPAIGN_IDENTITY')
        self.store=store;self.formal=formal;self.outcomes={};self.stopped=False
        for value in store.records():
            if not value['key'].startswith('attempt-'):continue
            r=value['record'];self._check(r)
            self.outcomes[(r['model_id'],r['attempt_index'])]=r['status']
            if r['status'] in ('TECHNICAL_FAILURE','UNASSESSABLE','UNKNOWN_SEND','NO_UPDATE','INCOMPLETE'):self.stopped=True

    def _check(self,r):
        schedules={s['model_id']:s['attempts'] for s in self.formal['schedules']}
        require(r['model_id'] in schedules and 0<=r['attempt_index']<2000,'P4B_ATTEMPT_ID')
        slot=schedules[r['model_id']][r['attempt_index']]
        require(r['slot_digest']==digest(slot),'P4B_ATTEMPT_SLOT_DRIFT')
        attempt_denominator([slot],{r['attempt_index']:r['status']})

    def save_outcome(self,model_id,index,status,*,evidence):
        require(not self.stopped,'P4B_CAMPAIGN_STOPPED')
        schedule=next(s['attempts'] for s in self.formal['schedules'] if s['model_id']==model_id)
        require(index==sum(m==model_id for m,_ in self.outcomes),'P4B_ATTEMPT_ORDER')
        require(status not in ('NOT_RUN','RUNNING') and bool(evidence),'P4B_FINAL_OUTCOME_REQUIRED')
        row={'model_id':model_id,'attempt_index':index,'slot_digest':digest(schedule[index]),
             'status':status,'evidence':evidence}
        self._check(row)
        self.store.append(row,key=f'attempt-{model_id}-{index:04d}')
        self.outcomes[(model_id,index)]=status
        if status in ('TECHNICAL_FAILURE','UNASSESSABLE','UNKNOWN_SEND','NO_UPDATE','INCOMPLETE'):self.stopped=True

    def denominator(self):
        return {s['model_id']:attempt_denominator(s['attempts'],{i:v for (m,i),v in self.outcomes.items() if m==s['model_id']})
                for s in self.formal['schedules']}

    def launch(self,**admission):
        # No callbacks, models, planner imports or action before admission.
        admit_business(**admission)
