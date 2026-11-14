"""B13–B15 bounded constructions. Actual kernel cases and control stubs separated."""
import copy
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import socket
import tempfile
import unittest
from jsonschema.exceptions import ValidationError
from unittest.mock import patch

from pct_baseline.contracts import digest,validate,read
from pct_baseline.execution import (GeometrySelector,CheckpointSink,build_config,execution_binding,run_constructed,preflight)
from p1b_fixtures import task,item
from semantic_pallet_planner.jev_select import execution,episode,transport
from semantic_pallet_planner.jev_select.stability import monitor
from semantic_pallet_planner.jev_select.stability.exact_contracts import ExactResult,load_config


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        root=os.environ.get('PCT_P1B_EVIDENCE_DIR')
        self.root=Path(root)/self._testMethodName if root else Path(self.temporary.name)
        self.root.mkdir(parents=True,exist_ok=True)
        self.addCleanup(patch.stopall)
        def forbidden(*args,**kwargs):raise AssertionError('network or credential access forbidden in P1-B')
        patch.object(socket.socket,'connect',forbidden).start()
        patch.object(socket.socket,'connect_ex',forbidden).start()
        patch.object(transport,'credential',forbidden).start()

    def run_case(self,t,name='run',selector_type=GeometrySelector):
        config=build_config(t);selector=selector_type(config)
        committed=[]
        original=execution.commit_physical
        def counted(*args,**kwargs):
            result=original(*args,**kwargs);committed.append(args[4].data)
            return result
        with patch.object(execution,'commit_physical',counted):
            result=run_constructed(t,config,self.root/name,selector=selector)
        return result,selector,committed,config

    def test_real_empty_singleton_multiple_and_rotated(self):
        cases=[('empty',item('too_big',(400,200,100)),(300,200,100),'STOP_NO_PHYSICAL_CANDIDATE',0),
               ('singleton',item('fit',(300,200,100)),(300,200,100),'ALL_ITEMS_PLACED',1),
               ('rotated',item('rotated',(200,300,100)),(300,200,100),'ALL_ITEMS_PLACED',1),
               ('multiple',item('small',(100,100,100)),(300,200,100),'ALL_ITEMS_PLACED',1)]
        for name,obj,c,reason,count in cases:
            ep,selector,commits,_=self.run_case(task(name,[obj],c),name)
            with self.subTest(name=name):
                self.assertEqual(ep['checkpoint']['reason'],reason)
                self.assertEqual(len(commits),count)
                decisions=[e for e in ep['events'] if e.get('decision_id')]
                selected=decisions[0]
                if name=='empty':self.assertIsNone(selected['selection']);self.assertIsNone(selected['monitor']);self.assertEqual(selector.calls,0)
                else:
                    self.assertEqual(selected['monitor']['status'],'STABLE')
                    self.assertEqual(selected['monitor']['result']['version'],'pct_stability_result_v3')
                    self.assertGreater(selected['monitor']['result']['kernel_calls'],0)
                    self.assertEqual(selector.calls,1 if name=='multiple' else 0)
                    self.assertEqual(selected['selection']['version'],'jev_selection_result_b1_v1')
                    self.assertEqual(selected['proposed_action'],selected['action'])
                    mapped=selected['context']['display_mapping'][selected['selection']['selected_display_id']]
                    self.assertEqual(selected['monitor']['binding']['candidate_digest'],mapped['candidate_digest'])
                if name=='rotated':self.assertEqual(ep['final_state']['placed_items'][0]['pose']['yaw_deg'],90)

    def test_real_stackable_and_capacity_boundaries(self):
        for name,stackable,cap,completed in [('allowed',True,1,True),('nonstackable',False,100,False),('overload',True,0.5,False)]:
            t=task(name,[item('base',stackable=stackable,capacity=cap),item('upper')],(100,100,200))
            ep,_,commits,_=self.run_case(t,name)
            with self.subTest(name=name):
                self.assertEqual(ep['summary']['loading']['completed'],completed)
                self.assertEqual(len(commits),2 if completed else 1)
                self.assertEqual(len(ep['final_state']['pending_items']),0 if completed else 1)
                if not completed:self.assertEqual(ep['checkpoint']['reason'],'STOP_NO_PHYSICAL_CANDIDATE')

    def test_control_stub_four_statuses_preserve_failed_loading_and_stage_order(self):
        # Actual candidate generation and original commit. Only assessment status is a stub.
        from semantic_pallet_planner.jev_select.stability import exact_adapter
        original_interface=monitor.kernel_interface
        for status in ('STABLE','UNSTABLE','UNASSESSABLE','ERROR'):
            t=task('stub_'+status,[item('base'),item('upper')],(100,100,200));cfg=build_config(t)
            calls=[];original_config=copy.deepcopy(cfg)
            def assessor(state,candidate,settings):
                calls.append(candidate.item_id)
                current='STABLE' if candidate.item_id=='base' else status
                # SELECTED must exist on disk before the assessor is called.
                stages=list((self.root/status/'stages').glob('*_SELECTED.json'))
                self.assertEqual(len(stages),len(calls))
                saved=read(sorted(stages)[-1]);self.assertIsNone(saved['pending_event']['monitor'])
                return ExactResult(status=current,reason_code='CONSTRUCTED_STUB_'+current,
                    state_digest=digest(asdict(state)),candidate_digest=digest(asdict(candidate)),candidate_id=candidate.item_id,
                    config_digest=digest(asdict(settings)),algorithm_identity=cfg['stability_monitor']['algorithm_identity'],
                    baseline_status='STABLE',first_bad_prefix=None,failed_item_id=None,height_delta_mm=None,
                    evaluated_pose=None,kernel_calls=0,diagnostics={'test_stub':True},duration_s=0)
            def interface(algorithm):
                _,loader,result_type,resource=original_interface(algorithm)
                return assessor,loader,result_type,resource
            commits=[];original_commit=execution.commit_physical
            def counted(*args,**kwargs):
                # MONITORED credential is persisted before original commit.
                stages=list((self.root/status/'stages').glob('*_MONITORED.json'))
                self.assertEqual(len(stages),len(commits)+1)
                answer=original_commit(*args,**kwargs);commits.append(answer);return answer
            with patch.object(monitor,'kernel_interface',interface),patch.object(execution,'commit_physical',counted):
                ep=run_constructed(t,cfg,self.root/status)
            with self.subTest(status=status):
                self.assertEqual(calls,['base','upper']);self.assertEqual(cfg,original_config)
                expected=2 if status=='STABLE' else 1
                self.assertEqual(len(commits),expected);self.assertEqual(ep['final_state']['placed_count'],expected)
                self.assertEqual(ep['summary']['loading']['placed_volume_mm3'],expected*100**3)
                self.assertEqual(ep['summary']['loading']['placed_mass_kg'],expected)
                if status!='STABLE':
                    failure=ep['events'][-1]
                    self.assertEqual(failure['before'],failure['after']);self.assertIsNone(failure['action'])
                    self.assertEqual(ep['checkpoint']['reason'],monitor.TERMINATIONS[status])
                    self.assertEqual(ep['final_state']['pending_items'][0]['item']['item_id'],'upper')
                    self.assertEqual(len(ep['final_state']['arrived_ids']),2)

    def test_real_exact_ancestor_instability_through_shared_engine(self):
        # Prescribed physical pools avoid depending on TopK reachability. Each
        # candidate passes the unchanged public evaluate_pose + physical oracle.
        from semantic_pallet_planner.domain import internal_item,restore_placed
        from semantic_pallet_planner.planner.constraints import evaluate_pose
        from semantic_pallet_planner.jev_select.config import generator_config
        from semantic_pallet_planner.jev_select.contracts import CandidateBundle
        from semantic_pallet_planner.jev_select.candidates import CandidateProvider
        t=task('real_unstable',[item('base',(140,200,100)),item('shelf',(200,200,100)),item('heavy',(100,200,100),mass=100)],(1000,800,600))
        poses={'base':(-70,-100,0),'shelf':(-100,-100,100),'heavy':(30,-100,200)}
        def prescribed(provider,state,req,generator,*,config):
            obj=state['pending_items'][0]['item'];x,y,z=poses[obj['item_id']]
            settings=copy.deepcopy(generator);settings['container']=state['container']
            size=obj['dimensions_mm'];candidate,error=evaluate_pose(internal_item(obj),restore_placed(state['placed_items']),x,y,z,size['length'],size['width'],0,settings)
            self.assertIsNone(error)
            physical=[candidate['visible']]
            value={'version':'jev_candidate_bundle_b1_v1','observation_digest':req['observation_digest'],'candidate_backend':'e2_original_v1',
                'generator_config_digest':digest(generator),'physical_candidates':physical,'physical_digest':digest(physical),
                'generation_counts':[],'selectable_pool':'unfiltered','selectable_candidates':[],'selectable_digest':digest([]),'policy_digest':None,
                'experiment_protocol':config['experiment_protocol'],'business_mode':'physical_only'}
            return CandidateBundle.from_dict(value)
        with patch.object(CandidateProvider,'build',prescribed):ep,selector,commits,cfg=self.run_case(t)
        self.assertEqual(len(commits),2)
        self.assertEqual(ep['checkpoint']['reason'],'PREDICTED_STATIC_INSTABILITY')
        self.assertEqual(ep['events'][-1]['monitor']['status'],'UNSTABLE')
        self.assertFalse(ep['events'][-1]['monitor']['result']['diagnostics'].get('test_stub',False))
        self.assertGreater(ep['events'][-1]['monitor']['result']['kernel_calls'],0)
        self.assertEqual(ep['summary']['loading']['placed_mass_kg'],2)
        self.assertEqual(ep['final_state']['pending_items'][0]['item']['mass_kg'],100)

    def test_preflight_identity_disabled_and_execution_admission_negatives(self):
        t=task('identity',[item('one')]);cfg=build_config(t);preflight(cfg)
        for kind in ('disabled','tolerance','algorithm','dependency','physical','source'):
            changed=copy.deepcopy(cfg)
            if kind=='disabled':changed['stability_monitor']={'enabled':False,'algorithm':None,'kernel_config':None,'algorithm_identity':None,'execution_environment':None}
            elif kind=='tolerance':changed['stability_monitor']['kernel_config']['mass_atol_kg']*=2
            elif kind=='algorithm':changed['stability_monitor']['algorithm_identity']['semantic_revision']='FORGED'
            elif kind=='dependency':changed['stability_monitor']['algorithm_identity']['dependencies']['scipy']='FORGED'
            elif kind=='physical':changed['runtime_identity']['physical_identity']='f'*64
            else:changed['runtime_identity']['strategy_identity']='f'*64
            # Resealing a changed monitor does not alter the expected actual identity.
            changed['runtime_identity']['monitor_identity']=digest(changed['stability_monitor'])
            with self.subTest(kind=kind),self.assertRaises((ValueError,ValidationError)):run_constructed(t,changed,self.root/kind)
            self.assertFalse((self.root/kind).exists())
        selector=GeometrySelector(cfg);sink=CheckpointSink(self.root/'negative_stages')
        with self.assertRaisesRegex(ValueError,'explicit_execution'):episode.run_episode(t,selector,cfg,job_id='X',method='geometry_b1',on_checkpoint=sink)
        permit=execution_binding(t,cfg,'X')
        with self.assertRaisesRegex(ValueError,'resume_memory_fork'):episode.run_episode(t,selector,cfg,job_id='X',method='geometry_b1',on_checkpoint=sink,extension_execution=permit,resume={})
        invalid=copy.deepcopy(t);invalid['exposure_status']='TRAIN_AND_IN_SAMPLE_RETEST';invalid['derived_task_digest']=digest({k:v for k,v in invalid.items() if k!='derived_task_digest'})
        with self.assertRaisesRegex(ValueError,'constructed_scope'):build_config(invalid)

    def test_real_kernel_boundaries_and_residuals(self):
        from semantic_pallet_planner.jev_select.stability.contracts import BoxInput,PlacedState
        from semantic_pallet_planner.jev_select.stability.exact_adapter import assess_candidate
        ground=BoxInput('ground',(100,100,100),1,(0,0,0));state=PlacedState((1000,800,600),(ground,))
        inputs=[('stable',BoxInput('top',(100,100,100),1,(0,0,100)),'STABLE'),
                ('unstable',BoxInput('top',(100,100,100),1,(90,0,100)),'UNSTABLE'),
                ('floating',BoxInput('top',(100,100,100),1,(0,0,101)),'UNASSESSABLE')]
        outcomes=[]
        for name,candidate,status in inputs:
            before=asdict(state);value=assess_candidate(state,candidate).to_dict()
            self.assertEqual(value['status'],status);self.assertEqual(before,asdict(state))
            if status=='STABLE':
                self.assertLess(abs(value['diagnostics']['global_mass_residual_kg']),1e-8)
                self.assertLess(max(map(abs,value['diagnostics']['global_moment_residual_kg_mm'])),1e-5)
            independent=None
            if status=='STABLE':
                # Recompute from input masses/centers and returned contact forces,
                # rather than accepting the solver's reported residual fields.
                reactions=value['diagnostics']['reactions']
                boxes=(*state.placed,candidate)
                centers={box.item_id:(box.bottom_center_mm[0]+state.container_mm[0]/2,
                    box.bottom_center_mm[1]+state.container_mm[1]/2) for box in boxes}
                residuals=[]
                for box in boxes:
                    outgoing=[r for r in reactions if r['upper']==box.item_id]
                    incoming=[r for r in reactions if r['lower']==box.item_id]
                    mass=math.fsum(r['mass_kg'] for r in outgoing)-box.mass_kg-math.fsum(r['mass_kg'] for r in incoming)
                    moments=[math.fsum(r['mass_kg']*r['point_mm'][axis] for r in outgoing)-box.mass_kg*centers[box.item_id][axis]-math.fsum(r['mass_kg']*r['point_mm'][axis] for r in incoming) for axis in (0,1)]
                    self.assertLess(abs(mass),1e-8)
                    self.assertLess(max(map(abs,moments)),1e-5)
                    residuals.append({'item_id':box.item_id,'mass_residual_kg':mass,'moment_residual_kg_mm':moments})
                self.assertTrue(all(r['mass_kg']>=0 and math.isfinite(r['mass_kg']) for r in reactions))
                ground_reactions=[r for r in reactions if r['lower'] is None]
                ground_mass=math.fsum(r['mass_kg'] for r in ground_reactions)-sum(b.mass_kg for b in boxes)
                self.assertLess(abs(ground_mass),1e-8)
                independent={'per_box':residuals,'global_mass_residual_kg':ground_mass}
            outcomes.append({'name':name,'input':asdict(candidate),'result':value,'independent_balance_check':independent})
        (self.root/'real_kernel.json').write_text(json.dumps(outcomes,indent=2)+'\n')

    def test_monitor_runtime_exception_is_persisted_error_without_commit(self):
        from semantic_pallet_planner.jev_select.stability import exact_adapter
        t=task('exception',[item('one',(300,200,100))],(300,200,100))
        with patch.object(exact_adapter,'assess_candidate',side_effect=RuntimeError('CONSTRUCTED_EXCEPTION')):
            ep,_,commits,_=self.run_case(t)
        self.assertEqual(commits,[])
        self.assertEqual(ep['checkpoint']['reason'],'STABILITY_MONITOR_ERROR')
        row=ep['events'][-1]['monitor']
        self.assertEqual(row['status'],'ERROR');self.assertEqual(row['result']['reason_code'],'MONITOR_EXCEPTION')
        self.assertEqual(ep['final_state']['pending_items'][0]['item']['item_id'],'one')
        self.assertEqual(ep['summary']['loading']['placed_mass_kg'],0)

    def test_invalid_selection_stops_before_monitor(self):
        from semantic_pallet_planner.jev_select.selector import SelectionResult
        class CorruptSelector(GeometrySelector):
            def select(self,*args,**kwargs):
                value=super().select(*args,**kwargs).data
                value['selected_candidate_id']='FORGED'
                return SelectionResult.from_dict(value)
        t=task('selection',[item('one')])
        with patch.object(monitor,'monitor_selected_action',side_effect=AssertionError('invalid selection was monitored')):
            ep,selector,commits,_=self.run_case(t,selector_type=CorruptSelector)
        self.assertEqual(selector.calls,1);self.assertEqual(commits,[])
        self.assertEqual(ep['checkpoint']['reason'],'pct_b1_selection_candidate_changed')
        self.assertIsNone(ep['events'][-1]['monitor'])

    def test_monitor_receives_independent_runtime_copies(self):
        t=task('copy',[item('one',(300,200,100))],(300,200,100))
        original=monitor.monitor_selected_action
        def adversarial(state,candidate,event,config):
            row=original(state,candidate,event,config)
            state['pending_items'].clear()
            candidate['pose']['x_mm']+=123
            event['selection']['selected_candidate_id']='MUTATED_COPY'
            return row
        with patch.object(monitor,'monitor_selected_action',adversarial):ep,_,commits,_=self.run_case(t)
        self.assertEqual(len(commits),1)
        self.assertEqual(ep['checkpoint']['reason'],'ALL_ITEMS_PLACED')
        self.assertEqual(ep['final_state']['placed_items'][0]['pose']['x_mm'],0)

    def test_new_records_closed_and_selection_saved_after_choice(self):
        from semantic_pallet_planner.jev_select.contracts import validate_schema
        from pct_baseline.contracts import validate
        outer=self
        class ObservingSelector(GeometrySelector):
            def select(self,context,**kwargs):
                stages=list((outer.root/'run/stages').glob('*_DECISION_READY.json'))
                outer.assertEqual(len(stages),1)
                outer.assertIsNone(read(stages[0])['pending_event']['selection'])
                outer.assertFalse(list((outer.root/'run/stages').glob('*_MONITORED.json')))
                return super().select(context,**kwargs)
        ep,selector,_,cfg=self.run_case(task('records',[item('one')]),selector_type=ObservingSelector)
        self.assertEqual(selector.calls,1)
        selection=next(e['selection'] for e in ep['events'] if e.get('selection'))
        for base,value in [('selection_result',selection),('checkpoint_b1_v1',ep['checkpoint'])]:
            validate_schema(base,value)
            for field in ('extra','version'):
                bad=copy.deepcopy(value)
                if field=='extra':bad['extra']=1
                else:bad['version']+='__v13'
                with self.subTest(base=base,field=field),self.assertRaises(ValueError):validate_schema(base,bad)

    def test_legacy_selection_result_and_monitored_dispatch_unchanged(self):
        import subprocess,types
        from test_b1_integration import PublicIntegrationTests
        from semantic_pallet_planner.jev_select.selector import result
        from semantic_pallet_planner.jev_select.contracts import DecisionContext
        helper=PublicIntegrationTests()
        _,_,_,context=helper.context(helper.config(new=False),n=1)
        source=subprocess.run(['git','show','25be41c789407abc3a7be48bbe80094127b44649:semantic_pallet_planner/src/semantic_pallet_planner/jev_select/selector.py'],text=True,capture_output=True,check=True).stdout
        baseline=types.ModuleType('original_selector');baseline.__package__='semantic_pallet_planner.jev_select'
        exec(compile(source,'25be41c7/selector.py','exec'),baseline.__dict__)
        for suffix in ('v4','v5','v13'):
            value=context.data;value['version']='jev_decision_context_'+suffix
            original_context=DecisionContext.from_dict(value)
            kwargs={'status':'singleton','source':'singleton','label':'C01'}
            self.assertEqual(result(original_context,**kwargs).data,baseline.result(original_context,**kwargs).data)
        self.assertTrue(monitor.is_monitored({'version':'jev_packaging_jm_no_memory_v13'}))
        self.assertFalse(monitor.is_monitored({'version':'jev_packaging_choice_v4'}))
