"""B16-B18: new-process interruption/recovery, drift, lock and saved-only proofs."""
import collections
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pct_baseline.contracts import read,digest,canonical
from pct_baseline.persistence import atomic_new,RecoveryError

ROOT=Path(__file__).resolve().parents[2]
WORKER='PCT/tests/p1c_worker.py'
PHASES=('DECISION_READY','SELECTED','MONITORED','COMMITTED')


def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
def calls(root):return [json.loads(line) for line in (root/'calls.jsonl').read_text().splitlines()] if (root/'calls.jsonl').exists() else []
def counts(root):return dict(collections.Counter(row['role'] for row in calls(root)))

def logical(value):
    if isinstance(value,dict):return {k:logical(v) for k,v in value.items() if k not in ('timings','duration_s','result_digest','credential_digest')}
    if isinstance(value,list):return [logical(v) for v in value]
    return value


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='p1c_test_',dir=ROOT/'PCT/outputs')
        cls.root=Path(os.environ.get('PCT_P1C_EVIDENCE_DIR',cls.temp.name)).resolve()
        cls.root.mkdir(parents=True,exist_ok=True)
        cls.env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='PCT/src:semantic_pallet_planner/src:PCT/tests')
        cls.command_count=0
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def invoke(self,action,root,extra=(),expected=0):
        argv=[sys.executable,WORKER,action,'--root',str(root),*extra]
        result=subprocess.run(argv,cwd=ROOT,env=self.env,text=True,capture_output=True)
        index=type(self).command_count;type(self).command_count+=1
        evidence={'argv':argv,'command':'"$NBU_PY" '+WORKER+' '+action+' --root '+str(root.relative_to(ROOT))+' '+' '.join(extra),
            'exit_code':result.returncode,'expected_exit':expected,'stdout':result.stdout,'stderr':result.stderr}
        (self.root/f'command_{index:03d}.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        self.assertEqual(result.returncode,expected,evidence)
        return json.loads(result.stdout.splitlines()[-1]) if result.stdout.strip() else None
    def prepare(self,name,scenario='stable',extra=()):
        root=self.root/name
        self.invoke('prepare',root,('--scenario',scenario,*extra));return root
    def reseal_tail(self,root,mutate):
        path=sorted((root/'journal').glob('*.json'))[-1];row=read(path);mutate(row['checkpoint'])
        cp=row['checkpoint'];cp['record_digest']=digest({k:v for k,v in cp.items() if k!='record_digest'})
        row['checkpoint_digest']=digest(cp);row['record_digest']=digest({k:v for k,v in row.items() if k!='record_digest'})
        path.write_text(canonical(row)+'\n')

    def test_four_stages_across_processes_real_and_stub(self):
        comparisons=[]
        for scenario in ('stable','unstable','stub_unstable'):
            baseline=self.prepare('baseline_'+scenario,scenario);self.invoke('run',baseline)
            reference=read(baseline/'episode.json');expected_counts=counts(baseline)
            self.invoke('verify',baseline)
            for phase in PHASES:
                with self.subTest(scenario=scenario,phase=phase):
                    root=self.prepare(scenario+'_'+phase,scenario)
                    self.invoke('run',root,('--cut',phase),75)
                    immutable={str(p.relative_to(root)):p.read_bytes() for p in (root/'journal').glob('*.json')}
                    before=calls(root);old_pid=before[0]['pid'];row=self.invoke('verify',root)
                    self.assertEqual(row['phase'],phase);self.assertEqual(row['forbidden_calls'],[]);self.assertFalse(row['scipy_imported'])
                    resumed=self.invoke('run',root)
                    self.assertNotEqual(old_pid,resumed['pid'])
                    after=read(root/'episode.json')
                    self.assertEqual(after['final_state'],reference['final_state'])
                    self.assertEqual(after['checkpoint']['reason'],reference['checkpoint']['reason'])
                    self.assertEqual(logical(after['events']),logical(reference['events']))
                    self.assertEqual(after['summary']['loading'],reference['summary']['loading'])
                    self.assertEqual(counts(root),expected_counts)
                    for name,raw in immutable.items():self.assertEqual((root/name).read_bytes(),raw)
                    latest=read(sorted((root/'journal').glob('*.json'))[-1])
                    self.assertEqual(latest['checkpoint']['phase'],'TERMINATED')
                    self.invoke('verify',root)
                    unchanged=hashes(root);self.invoke('run',root)
                    self.assertEqual(hashes(root),unchanged)
                    comparisons.append({'scenario':scenario,'phase':phase,'old_pid':old_pid,'resume_pid':resumed['pid'],
                        'actual_cross_process_role_counts':counts(root),'baseline_counts':expected_counts,
                        'saved_journal_prefix_byte_identical':True,'logical_events_equal':True,'final_state_loading_termination_equal':True,
                        'event_comparison_exclusions':['timings','duration_s','result_digest','credential_digest'],
                        'note':'timing-dependent monitor seals differ between separate baseline runs, but saved monitor payloads/seals themselves never change on resume'})
        (self.root/'cross_process_comparisons.json').write_text(json.dumps(comparisons,indent=2)+'\n')

    def test_lock_contention_and_single_writer(self):
        root=self.prepare('lock')
        argv=[sys.executable,WORKER,'hold-lock','--root',str(root)]
        holder=subprocess.Popen(argv,cwd=ROOT,env=self.env,text=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.addCleanup(lambda:holder.poll() is None and holder.kill())
        self.assertEqual(holder.stdout.readline().strip(),'LOCKED')
        before=hashes(root)
        rejected=self.invoke('run',root,expected=1)
        self.assertIn('JOB_LOCK_CONTENDED',rejected['detail']);self.assertEqual(hashes(root),before)
        holder.stdin.write('\n');holder.stdin.flush();stdout,stderr=holder.communicate(timeout=10)
        self.assertEqual(holder.returncode,0)
        (self.root/'lock_holder.json').write_text(json.dumps({'argv':argv,'pid':holder.pid,'exit_code':holder.returncode,'ready':'LOCKED','stdout':stdout,'stderr':stderr},indent=2)+'\n')
        self.invoke('run',root);self.invoke('verify',root)

    def test_drift_corruption_partial_save_and_unknown_commit(self):
        base=self.prepare('negative_parent');self.invoke('run',base,('--cut','DECISION_READY'),75)
        failures=[]
        for kind in ('task','config','candidate','strategy','sequence','json','monitor','partial'):
            root=self.root/('negative_'+kind);shutil.copytree(base,root)
            if kind in ('task','config','strategy'):
                # Deliberately edited header without silently re-signing old records.
                path=root/'header.json';value=read(path)
                if kind=='task':value['task']['items'][0]['mass_kg']+=1
                elif kind=='config':value['config']['display_order_seed']+=1
                else:value['identities']['policy']['strategy_identity']='f'*64
                path.write_text(canonical(value)+'\n')
            elif kind=='candidate':
                def mutate(cp):
                    bundle=cp['pending_event']['bundle'];bundle['physical_candidates'][0]['pose']['x_mm']+=1
                    bundle['selectable_candidates']=copy.deepcopy(bundle['physical_candidates'])
                    bundle['physical_digest']=digest(bundle['physical_candidates']);bundle['selectable_digest']=bundle['physical_digest']
                self.reseal_tail(root,mutate)
            elif kind=='sequence':(root/'journal/00000000.json').unlink()
            elif kind=='json':sorted((root/'journal').glob('*.json'))[-1].write_text('{')
            elif kind=='monitor':
                # A fresh stopped MONITORED archive to attack a stored credential.
                shutil.rmtree(root);self.invoke('prepare',root);self.invoke('run',root,('--cut','MONITORED'),75)
                def mutate(cp):
                    row=cp['pending_event']['monitor'];row['result']['candidate_digest']='f'*64
                    row['result_digest']=digest(row['result']);row['credential_digest']=digest({k:v for k,v in row.items() if k!='credential_digest'})
                self.reseal_tail(root,mutate)
            else:
                # Actual write/rename failure leaves a partial pending record;
                # no automatic retry or deletion makes it appear successful.
                with patch('pct_baseline.persistence.os.replace',side_effect=OSError('INJECTED_RENAME_FAILURE')):
                    with self.assertRaisesRegex(RecoveryError,'ATOMIC_SAVE_FAILED'):
                        atomic_new(root/'journal/99999999.json',{'test':'partial'})
            before=hashes(root);result=self.invoke('run',root,expected=1)
            self.assertEqual(hashes(root),before)
            failures.append({'kind':kind,'detail':result['detail'],'archive_unchanged_after_rejection':True})
        result=self.invoke('run',base,('--dependency-drift',),1)
        self.assertIn('RECOVERY_DEPENDENCY_DRIFT',result['detail']);failures.append({'kind':'injected_current_dependency','detail':result['detail']})
        probe=self.root/'frozen_probe.py';probe.write_text('# frozen\n')
        source=self.prepare('source_drift',extra=('--extra-source-file',str(probe.relative_to(ROOT))))
        self.invoke('run',source,('--cut','DECISION_READY'),75)
        probe.write_text('# changed\n');result=self.invoke('run',source,expected=1)
        self.assertIn('RECOVERY_SOURCE_DRIFT',result['detail']);probe.write_text('# frozen\n')
        failures.append({'kind':'actual_current_source_bytes','detail':result['detail']})
        unknown=self.prepare('unknown_commit');self.invoke('run',unknown,('--cut','MONITORED'),75)
        cp=read(sorted((unknown/'journal').glob('*.json'))[-1])['checkpoint'];event=cp['pending_event']
        atomic_new(unknown/'commit_intent.json',{'version':'pct_b1_commit_intent_v1','decision_id':event['decision_id'],
            'before_digest':digest(event['before']),'selection_digest':digest(event['selection'])})
        before=counts(unknown);result=self.invoke('run',unknown,expected=1)
        self.assertIn('COMMIT_OUTCOME_UNKNOWN',result['detail']);self.assertEqual(counts(unknown),before)
        failures.append({'kind':'unknown_commit_window','detail':result['detail']})
        (self.root/'negative_results.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2)+'\n')

    def test_saved_validator_no_business_and_read_only(self):
        root=self.prepare('validator');self.invoke('run',root)
        before=hashes(root);result=self.invoke('verify',root)
        self.assertEqual(result['forbidden_calls'],[]);self.assertFalse(result['scipy_imported']);self.assertEqual(hashes(root),before)
        for role in ('selector','transport','candidate','order','lp'):
            result=self.invoke('probe',root,('--probe',role))
            self.assertEqual(result['status'],'BLOCKED');self.assertEqual(len(result['violations']),1)
            self.assertEqual(hashes(root),before)
        from pct_baseline.execution import GeometrySelector,CheckpointSink,execution_binding,build_config
        from p1b_fixtures import task,item
        from semantic_pallet_planner.jev_select.episode import run_episode
        old_task=task('old_resume_rejected',[item('one')]);cfg=build_config(old_task)
        with self.assertRaisesRegex(ValueError,'resume_memory_fork'):
            run_episode(old_task,GeometrySelector(cfg),cfg,job_id=old_task['task_id'],method='geometry_b1',resume={},
                on_checkpoint=CheckpointSink(self.root/'unused'),extension_execution=execution_binding(old_task,cfg,old_task['task_id']))

    def test_additional_saved_ledger_and_terminal_negatives(self):
        supplied=os.environ.get('PCT_P1C_REFERENCE_JOB')
        reference=Path(supplied) if supplied else self.prepare('ledger_reference')
        if supplied is None:self.invoke('run',reference)
        original=hashes(reference);results=[]
        for kind in ('summary','episode_state','terminal_reason','model_placeholder','unknown_field'):
            root=self.root/('saved_'+kind);shutil.copytree(reference,root)
            if kind in ('summary','episode_state'):
                value=read(root/'episode.json')
                if kind=='summary':value['summary']['loading']['placed_mass_kg']+=1
                else:value['final_state']['placed_count']+=1
                (root/'episode.json').write_text(canonical(value)+'\n')
            elif kind=='terminal_reason':self.reseal_tail(root,lambda cp:cp.update(reason='FORGED_COMPLETE'))
            else:
                value=read(root/'header.json')
                if kind=='model_placeholder':value['identities']['model_weights']={'status':'NOT_IMPLEMENTED','sha256':'f'*64}
                else:value['admission']['unknown']=True
                (root/'header.json').write_text(canonical(value)+'\n')
            before=hashes(root);value=self.invoke('verify',root,expected=1)
            self.assertEqual(hashes(root),before)
            results.append({'kind':kind,'diagnostic':value['detail'],'files_unchanged':True})
        self.assertEqual(hashes(reference),original)
        (self.root/'saved_ledger_negatives.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')

    def test_committed_intent_cleanup_never_recommits(self):
        supplied=os.environ.get('PCT_P1C_REFERENCE_JOB')
        if supplied:
            reference=Path(supplied).parent/'stable_COMMITTED'
        else:
            reference=self.prepare('intent_reference');self.invoke('run',reference,('--cut','COMMITTED'),75)
        root=self.root/'known_commit_intent';shutil.copytree(reference,root)
        paths=sorted((root/'journal').glob('*.json'))
        index=next(i for i,p in enumerate(paths) if read(p)['checkpoint']['phase']=='COMMITTED')
        for path in paths[index+1:]:path.unlink()
        (root/'episode.json').unlink(missing_ok=True)
        cp=read(paths[index])['checkpoint'];event=cp['pending_event']
        atomic_new(root/'commit_intent.json',{'version':'pct_b1_commit_intent_v1','decision_id':event['decision_id'],
            'before_digest':digest(event['before']),'selection_digest':digest(event['selection'])})
        before=counts(root);prefix={p.name:p.read_bytes() for p in paths[:index+1]}
        value=self.invoke('verify',root);self.assertEqual(value['phase'],'COMMITTED')
        self.assertTrue((root/'commit_intent.json').exists())
        value=self.invoke('run',root);self.assertEqual(value['status'],'ALL_ITEMS_PLACED')
        self.assertEqual(counts(root),before);self.assertFalse((root/'commit_intent.json').exists())
        for name,raw in prefix.items():self.assertEqual((root/'journal'/name).read_bytes(),raw)
        self.invoke('verify',root)
