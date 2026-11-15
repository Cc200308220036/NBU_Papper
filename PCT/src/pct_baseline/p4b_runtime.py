"""Independent P4-B-0 recovery/observer protocol; no business imports.

Public run_episode integration is intentionally not registered by this PCT-only
change. No P3 protocol is impersonated. Business launch fails closed.
"""
import copy
from collections import Counter
from .contracts import digest, require
from .p4b_storage import checked, seal, FALLBACK

EXECUTION='pct_p4b_execution_v1'
RECOVERY='pct_p4b_recovery_v1'
WAL='pct_p4b_wal_v1'
STAGES={'READY':{'READY','DECISION_READY','TERMINATED'},
        'DECISION_READY':{'SELECTED','TERMINATED'},'SELECTED':{'MONITORED'},
        'MONITORED':{'COMMITTED','TERMINATED'},'COMMITTED':{'READY','TERMINATED'},'TERMINATED':set()}


def recovery_work(phase):
    require(phase in STAGES,'P4B_PHASE')
    return {'READY':['public_next_event'],'DECISION_READY':['saved_pool_select'],
            'SELECTED':['saved_selection_monitor'],'MONITORED':['saved_monitor_commit_or_stop'],
            'COMMITTED':['saved_committed_finalize'],'TERMINATED':[]}[phase]


class StageJournal:
    """JournalSink-compatible callable with append-only event refs and hot WAL.

    One event is stored once on completion; each checkpoint stores only the
    current state/pending event plus refs to the newly completed event suffix.
    No cumulative events are copied. Per-stage shards bounded by Store.limit.
    All counters describe durable facts, never presumed callback executions.
    """
    def __init__(self,store):
        self.rng_binding=None
        self.store=store;self.rows=[];self.events=[];self.counts=Counter()
        self.indexed={v['key']:v['record'] for v in store.records()}
        for path in sorted((store.root/'wal').glob('*.json')):
            row=checked(path)
            require(path.stem==f'{len(self.rows):08d}' and row['version'] in (WAL,'pct_p4b_rng_wal_v3') and
                    row['previous']==(self.rows[-1]['seal'] if self.rows else digest(store.identity)), 'P4B_WAL_CHAIN')
            self._accept(row)
        indexed=self.indexed
        refs={r['key'] for row in self.rows for r in row['events']}
        require(refs=={k for k in indexed if k.startswith('event-')},'P4B_ORPHAN_EVENT')

    def _accept(self,row):
        require(row['identity']==self.store.identity,'P4B_WAL_IDENTITY_DRIFT')
        if self.rows:require(row['checkpoint']['phase'] in STAGES[self.rows[-1]['checkpoint']['phase']], 'P4B_STAGE_ORDER')
        indexed=self.indexed
        for ref in row['events']:
            require(ref['key'] in indexed and digest(indexed[ref['key']])==ref['digest'],'P4B_EVENT_REF')
            self.events.append(indexed[ref['key']])
        self.counts.update(row['counts']);self.rows.append(row)

    @property
    def checkpoint(self):
        if not self.rows:return None
        cp=copy.deepcopy(self.rows[-1]['checkpoint']);cp['events']=copy.deepcopy(self.events);return cp

    def __call__(self,checkpoint):
        cp=copy.deepcopy(checkpoint);events=cp.pop('events');phase=cp['phase']
        require(phase in STAGES and events[:len(self.events)]==self.events,'P4B_HISTORY_CHANGED')
        old=self.checkpoint
        if old==checkpoint:return
        if old:
            require(phase in STAGES[old['phase']], 'P4B_STAGE_ORDER')
            pending=old.get('pending_event')
            if pending:
                nxt=cp.get('pending_event') or (events[-1] if len(events)>len(self.events) else None)
                require(nxt is not None and nxt['decision_id']==pending['decision_id'],'P4B_PENDING_CHANGED')
                for key in ('before','observation','bundle','context','selection','proposed_action','monitor'):
                    if pending.get(key) is not None:require(nxt.get(key)==pending[key],'P4B_SAVED_FACT_CHANGED')
        refs=[]
        for event in events[len(self.events):]:
            key=f'event-{len(self.events)+len(refs):08d}'
            self.store.append(event,key=key);self.indexed[key]=copy.deepcopy(event);refs.append({'key':key,'digest':digest(event)})
        counts={};pending=cp.get('pending_event') or {}
        if phase=='DECISION_READY':
            counts['candidate_generations']=1
            counts['candidate_actions']=len(pending['bundle']['physical_candidates'])
        if phase=='SELECTED':
            singleton=pending['selection']['status']=='singleton'
            counts['singleton_selections' if singleton else 'choice_selections']=1
        if phase=='MONITORED':counts['monitor_results_persisted']=1
        if phase=='COMMITTED':counts['commits_persisted']=1
        row=seal({'version':WAL,'identity':self.store.identity,'checkpoint':cp,'events':refs,'counts':counts,
                  'previous':self.rows[-1]['seal'] if self.rows else digest(self.store.identity)})
        if self.rng_binding is not None:
            from . import p4b_rng as rng
            row.pop('seal');row['version']=rng.WAL
            owner={'sequence':len(self.rows),'phase':phase,'previous':row['previous']}
            state=rng.capture()
            row['rng']=rng.envelope(state,state,binding=self.rng_binding,owner=owner,
                    result={'checkpoint':cp,'events':refs})
            row=seal(row)
        self.store.put(self.store.root/'wal'/f'{len(self.rows):08d}.json',row)
        self._accept(row)

    def session(self):
        phase=self.checkpoint['phase'] if self.rows else 'READY'
        counts={'saved_selection_reuses':int(phase in ('SELECTED','MONITORED')),
                'saved_monitor_reuses':int(phase=='MONITORED'),
                'saved_committed_reuses':int(phase=='COMMITTED')}
        return seal({'version':RECOVERY,'start_phase':phase,'resume_work':recovery_work(phase),
                     'planned_reuses':counts,'counts':{},'durable_counts':dict(self.counts)})

    def record_reuse(self,kind,decision_id):
        require(kind in ('saved_selection_reuses','saved_monitor_reuses','saved_committed_reuses'),'P4B_REUSE_KIND')
        phase=self.checkpoint['phase'] if self.rows else 'READY'
        require((kind=='saved_selection_reuses' and phase in ('SELECTED','MONITORED')) or
                (kind=='saved_monitor_reuses' and phase=='MONITORED') or
                (kind=='saved_committed_reuses' and phase=='COMMITTED'),'P4B_REUSE_PHASE')
        require(self.checkpoint['pending_event']['decision_id']==decision_id,'P4B_REUSE_DECISION')
        return self.store.append({'version':RECOVERY,'kind':kind,'decision_id':decision_id},
                                 key=f'reuse-{len(list((self.store.root/"index").glob("reuse-*.json"))):08d}')

    def record_forward(self,decision_id,*,singleton,record_reused=False):
        """Selection record publication observer, not a presumed SELECTED forward."""
        return self.store.append({'version':EXECUTION,'decision_id':decision_id,
               'policy_choice_forwards':int(not singleton and not record_reused),
               'singleton_critic_forwards':int(singleton and not record_reused),
               'selection_record_reuses':int(record_reused)},key=f'forward-{len(list((self.store.root/"index").glob("forward-*.json"))):08d}')


def admit_business(*,accepted_identity=None, resource_receipt=None, authorization=None):
    require(accepted_identity is not None,'P4B_ACCEPTED_EXECUTION_IDENTITY_MISSING')
    require(resource_receipt is not None and resource_receipt.get('accepted') is True and
            resource_receipt.get('free_bytes',0)>=FALLBACK,'P4B_RESOURCE_GATE')
    require(authorization is not None,'P4B_IMPLEMENTATION_AUTHORIZATION_MISSING')
    # Cannot use P3's closed schema or silently bypass the public resolver.
    raise RuntimeError('P4B_PUBLIC_ROUTING_NOT_REGISTERED_REQUIRES_SEPARATE_SCOPE')


def attempt_denominator(schedule, outcomes):
    require(len({s['attempt_index'] for s in schedule})==len(schedule),'P4B_SCHEDULE_DUPLICATE')
    require(set(outcomes)<=set(s['attempt_index'] for s in schedule),'P4B_UNKNOWN_ATTEMPT')
    from .p4a import STATES
    require(all(v in STATES for v in outcomes.values()),'P4B_ATTEMPT_STATUS')
    return [dict(slot,status=outcomes.get(slot['attempt_index'],'NOT_RUN')) for slot in schedule]
