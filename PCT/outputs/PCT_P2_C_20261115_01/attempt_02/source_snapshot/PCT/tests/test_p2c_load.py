"""B26-B28 public load single-step tests; no orders/generation/LP."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import socket
import numpy as np
import torch
from pct_baseline.contracts import sha,digest
from pct_baseline.load_encoding import encode_load,aggregate,EncodedLoad,FEATURE_CONTRACT
from pct_baseline.geo_encoding import encode_geometry
from pct_baseline import load_model as lm,geo_model as gm
from pct_baseline.load_selector import PCTLoadSelector,save_selection
from p2b_fixtures import fixture,rebind
from p1b_fixtures import task,item

class LoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
        from pct_baseline.execution import build_config
        cls.config=build_config(task('P2C_CARRIER',[item('current')]))
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.out=Path(os.environ.get('PCT_P2C_EVIDENCE_DIR',cls.tmp.name));cls.out.mkdir(parents=True,exist_ok=True)
        cls.wp=cls.out/'weight_tensors.json';core=lm.new_core()
        cls.wp.write_text(json.dumps({k:{'dtype':str(v.dtype),'shape':list(v.shape),'values':v.tolist()} for k,v in core.state_dict().items()}))
        cls.mp=cls.out/'model_manifest.json';cls.mp.write_text(json.dumps(lm.make_manifest(cls.wp,provenance={'kind':'RANDOM_INITIALIZATION_ENGINEERING_ONLY','seed':0,'evidence':'new_core seed0; no training'}),indent=2))
        (cls.out/'pre_inference_weights_identity.json').write_text(json.dumps({'weights_sha256':sha(cls.wp),'model_manifest_sha256':sha(cls.mp),'provenance':'RANDOM_INITIALIZATION_ENGINEERING_ONLY','generated_before_forward':True},indent=2))
        cls.model=lm.load_model(cls.mp,cls.wp,expected_manifest_sha256=sha(cls.mp));cls.rejections=[]

    def setUp(self):
        self.addCleanup(patch.stopall)
        def forbidden(*a,**kw):raise AssertionError('P2C_FORBIDDEN_ENTRY')
        from semantic_pallet_planner.jev_select import candidates,episode,transport,execution
        from semantic_pallet_planner.jev_select.stability import monitor
        import scipy.optimize
        for obj,name in [(socket.socket,'connect'),(socket.socket,'connect_ex'),(candidates.CandidateProvider,'build'),(episode,'run_episode'),(transport,'credential'),(execution,'commit_physical'),(monitor,'monitor_selected_action'),(scipy.optimize,'linprog')]:patch.object(obj,name,forbidden).start()

    def dump(self,name,data):
        (self.out/(name+'.json')).write_text(json.dumps(data,indent=2,allow_nan=False))

    def reject(self,name,fn):
        try:fn()
        except (ValueError,KeyError,TypeError,RuntimeError,OSError) as e:
            self.rejections.append({'name':name,'error':str(e)});return
        self.fail('not rejected '+name)

    def known(self,before=(0,0),count=3):
        ctx,c=fixture(self.config,placed=True,count=count);v=ctx.data;s=v['model_state']
        base=s['placed_objects'][0];s['placed_objects']=[copy.deepcopy(base),copy.deepcopy(base)]
        for i,(o,cap,used) in enumerate(zip(s['placed_objects'],[27,9],before)):
            o.update(object_id=f'B{i+1:03d}',max_top_load_kg=cap,current_top_load_kg=used,remaining_top_load_kg=cap-used,effective_top_permission_kg=cap,capacity_utilization=used/cap)
        s['available_objects'][0]['mass_kg']=10
        for cr in v['criteria'].values():
            cr['load_changes']=[{'object_id':o['object_id'],'before_top_load_kg':used,'increment_top_load_kg':5,'after_top_load_kg':used+5,'max_top_load_kg':cap,'remaining_top_load_kg':cap-used-5} for o,cap,used in zip(s['placed_objects'],[27,9],before)]
        return rebind(v),c

    def test_b26_values_fields_and_boundaries(self):
        for name,before,util,remaining in [('p0',(0,0),5/9,4),('nonzero',(3,2),7/9,2)]:
            ctx,c=self.known(before);e=encode_load(ctx);a=e.data['packed']
            np.testing.assert_allclose(a[40][9:12],[util,remaining/9,1],rtol=1e-7)
            self.assertEqual(a[40][:6],[float(np.float32(x/1000)) for x in e.data['actual_leaf_corners_mm_float64'][0]])
            self.assertEqual(a[56][:3],[float(np.float32(x/1000)) for x in [100.25,60.5,40.75]])
            self.dump(name,{'context':ctx.data,'candidates':c,'encoding':e.data,'hand':{'utilization':util,'remaining_kg':remaining,'applicable':True}})
        ctx,c=fixture(self.config,placed=True);v=ctx.data;o=v['model_state']['placed_objects'][0]
        o.update(stackable=False,remaining_top_load_kg=0,effective_top_permission_kg=0,capacity_utilization=None,utilization_status='NOT_APPLICABLE')
        e=encode_load(v);self.assertEqual(e.data['packed'][0][7],0);self.assertEqual(e.data['packed'][40][9:12],[0,0,0])
        self.dump('nonstackable_empty',{'context':v,'encoding':e.data})
        for field in ['mass_kg','stackable','max_top_load_kg','current_top_load_kg','remaining_top_load_kg']:
            bad=copy.deepcopy(v);del bad['model_state']['placed_objects'][0][field];self.reject('missing_'+field,lambda:encode_load(bad))
        ctx,c=self.known();v=ctx.data;objects={o['object_id']:o for o in v['model_state']['placed_objects']};changes=v['criteria']['C01']['load_changes']
        zero=copy.deepcopy(changes);zero.append({'object_id':'B003','before_top_load_kg':0,'increment_top_load_kg':0,'after_top_load_kg':0,'max_top_load_kg':1,'remaining_top_load_kg':1})
        objects['B003']={**copy.deepcopy(objects['B001']),'current_top_load_kg':0,'max_top_load_kg':1}
        self.assertEqual(aggregate(zero,objects),[5/9,4/9,1])
        for name,cap,stack in [('zero_capacity',0,True),('nonstackable_positive',27,False)]:
            ob=copy.deepcopy(objects);ob['B001'].update(max_top_load_kg=cap,stackable=stack);ch=copy.deepcopy(changes);ch[0].update(max_top_load_kg=cap,remaining_top_load_kg=0)
            self.reject(name,lambda:aggregate(ch,ob))
        self.dump('positive_set_only',{'objects':objects,'changes':zero,'aggregate':aggregate(zero,objects)})

    def test_b27_variations_and_geometry_unchanged(self):
        ctx,c=self.known();base=encode_load(ctx);geo=encode_geometry(ctx)
        results=[]
        for name,mut,expected in [
            ('mass',lambda v:v['model_state']['available_objects'][0].update(mass_kg=11),[(56,3)]),
            ('capacity',lambda v:v['model_state']['available_objects'][0].update(max_top_load_kg=999,remaining_top_load_kg=999),[(56,5)]),
            ('placed_mass',lambda v:v['model_state']['placed_objects'][0].update(mass_kg=2),[(0,6)])]:
            v=ctx.data;mut(v);e=encode_load(v);g=encode_geometry(v)
            diff=[tuple(int(y) for y in x) for x in np.argwhere(np.array(e.data['packed'])!=np.array(base.data['packed']))]
            self.assertEqual(diff,expected);self.assertEqual(g.data['feature_digest'],geo.data['feature_digest']);self.assertEqual(e.data['mapping'],base.data['mapping'])
            results.append({'name':name,'context':v,'encoding':e.data,'geometry':g.data,'changed_fields':diff})
        v=ctx.data;v['model_state']['placed_objects'][1].update(max_top_load_kg=18,remaining_top_load_kg=18)
        for cr in v['criteria'].values():cr['load_changes'][1].update(max_top_load_kg=18,remaining_top_load_kg=13)
        changed=encode_load(v);self.assertEqual(encode_geometry(v).data['feature_digest'],geo.data['feature_digest'])
        self.assertEqual(changed.data['mapping'],base.data['mapping'])
        np.testing.assert_allclose(changed.data['packed'][40][9:12],[5/18,13/9,1],rtol=1e-7)
        results.append({'name':'affected_capacity','context':v,'encoding':changed.data,'expected_changed':'placed1 capacity/remaining; leaves utilization/remaining'})
        self.dump('b27',{'base_context':ctx.data,'base':base.data,'geometry':geo.data,'variants':results})

    def test_b28_isolation_and_entry_rejection(self):
        ctx,c=self.known();base=encode_load(ctx);cases=[]
        for field in ['future_order','source_id','witness','monitor_label','reaction_forces','test_score','terminal_state']:
            v=ctx.data;v[field]={'private':'changed'};self.assertEqual(encode_load(v).data,base.data)
            illegal=rebind(v);selector=PCTLoadSelector(self.config,self.model)
            self.reject('closed_entry_'+field,lambda:selector.bind_candidates(illegal,c));cases.append({'field':field,'raw_projection_equal':True,'entry_rejected':True})
        self.dump('b28',{'public_context':ctx.data,'encoding':base.data,'cases':cases,'network_query':'packed only; no retrieval'})

    def test_network_batch_routes_binding_and_rejections(self):
        items=[fixture(self.config,count=n,placed=True) for n in [1,3,16]];es=[encode_load(ctx) for ctx,c in items]
        batch=self.model.infer(es);singles=[self.model.infer([e])[0] for e in es]
        for e,b,s in zip(es,batch,singles):
            np.testing.assert_allclose(b['probabilities'],s['probabilities'],atol=1e-6,rtol=1e-5);self.assertEqual(b['leaf_index'],s['leaf_index']);self.assertEqual(b['probabilities'][e.data['candidate_count']:],[0.]*(16-e.data['candidate_count']))
        self.dump('batch',{'contexts':[ctx.data for ctx,c in items],'encodings':[e.data for e in es],'batch':batch,'singles':singles})
        for n in [0,1,3]:
            ctx,c=fixture(self.config,count=n);selector=PCTLoadSelector(self.config,self.model);selector.bind_candidates(ctx,c);before=self.model.calls
            selected=selector.select(ctx,decision_id='P2B_D0000');self.assertEqual(self.model.calls-before,int(n>1))
            if n:
                record=selector.last_record;save_selection(self.out/f'selection_{n}.json',record)
                with patch.object(self.model,'infer',side_effect=AssertionError('saved must not infer')):self.assertEqual(selector.reuse_saved(record,ctx,decision_id='P2B_D0000').data,selected.data)
                bad=copy.deepcopy(record);bad['exact_candidate']['pose']['x_mm']+=1;bad['record_digest']=digest({k:v for k,v in bad.items() if k!='record_digest'})
                self.reject('saved_action_'+str(n),lambda:selector.reuse_saved(bad,ctx,decision_id='P2B_D0000'))
            self.dump('route_'+str(n),{'config':self.config,'context':ctx.data,'candidates':c,'record':selector.last_record,'model_calls_delta':self.model.calls-before})
        self.reject('empty_forward',lambda:self.model.infer([encode_load(fixture(self.config,count=0)[0])]))
        self.reject('leaf_overflow',lambda:encode_load(fixture(self.config,count=17)[0]))
        ctx,c=fixture(self.config,placed=True,count=16);v=ctx.data;o=v['model_state']['placed_objects'][0];v['model_state']['placed_objects']=[{**copy.deepcopy(o),'object_id':f'P{i}'} for i in range(40)]
        e=encode_load(v);self.model.infer([e]);self.dump('capacity40',{'context':v,'encoding':e.data})
        v['model_state']['placed_objects'].append({**o,'object_id':'overflow'});self.reject('placed_overflow',lambda:encode_load(v))
        for idx in [-1,16,True,1.0,None]:self.reject('index_'+str(idx),lambda:es[0].resolve(idx))
        p=torch.tensor([batch[1]['probabilities']]);value=torch.zeros(1,1);idx=torch.tensor([[batch[1]['leaf_index']]]);h=torch.zeros(1)
        for name,pp,vv,ii,hh in [('nan',p*float('nan'),value,idx,h),('shape',p[:,:15],value,idx,h),('padding',torch.ones(1,16)/16,value,idx,h),('value_inf',p,value+float('inf'),idx,h),('index_float',p,value,idx.float(),h),('index_invalid',p,value,idx+99,h)]:self.reject(name,lambda:lm.checked_outputs([es[1]],pp,vv,ii,hh))
        bad=es[1].data;bad['packed'][0][11]=1;self.reject('unused_field',lambda:self.model.infer([EncodedLoad(bad)]))

    def test_strict_model_identity(self):
        geo=Path('PCT/outputs/PCT_P2_B_20261115_01')
        self.reject('geo_into_load',lambda:lm.load_model(geo/'model_manifest.json',geo/'weight_tensors.json',expected_manifest_sha256=sha(geo/'model_manifest.json')))
        self.reject('load_into_geo',lambda:gm.load_model(self.mp,self.wp,expected_manifest_sha256=sha(self.mp)))
        self.reject('wrong_pin',lambda:lm.load_model(self.mp,self.wp,expected_manifest_sha256='0'*64))
        for field in ['version','feature_contract','architecture','runtime','parameters','weights_sha256','extra']:
            m=json.loads(self.mp.read_text());m[field]='bad';p=self.out/f'bad_{field}.json';p.write_text(json.dumps(m));self.reject('manifest_'+field,lambda:lm.load_model(p,self.wp,expected_manifest_sha256=sha(p)))
        raw=json.loads(self.wp.read_text());k=next(iter(raw));raw[k]['values'][0][0]+=1;p=self.out/'bad_weights.json';p.write_text(json.dumps(raw));self.reject('weight_bytes',lambda:lm.load_model(self.mp,p,expected_manifest_sha256=sha(self.mp)))
        with torch.no_grad():
            param=next(self.model._model.parameters());old=param.clone();param.add_(1)
            self.reject('runtime_weight_mutation',self.model.check_identity);param.copy_(old)
        self.model._model.train();self.reject('runtime_train',self.model.check_identity);self.model._model.eval()
        self.model.check_identity();self.dump('rejections',self.rejections)
