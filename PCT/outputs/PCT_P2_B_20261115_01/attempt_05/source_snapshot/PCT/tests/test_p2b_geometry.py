"""B23-B25 isolated geometry encoding, strict load and one-step binding tests."""
import copy
import json
import math
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import torch
from pct_baseline.contracts import ContractError,digest,sha
from pct_baseline.geo_encoding import EncodedGeometry,encode_geometry,inverse_corner,verify_candidates
from pct_baseline.geo_model import make_manifest,load_model,checked_outputs
from pct_baseline.geo_selector import PCTGeoSelector,save_selection,validate_saved_selection
from p1b_fixtures import item,task
from p2b_fixtures import fixture,rebind,ROOT


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
        from pct_baseline.execution import build_config
        cls.config=build_config(task('P2B_CARRIER',[item('current')]))
        cls.weights=ROOT/'PCT/outputs/PCT_P2_A_20261114_01/weight_tensors.json'
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.root=Path(os.environ.get('PCT_P2B_EVIDENCE_DIR',cls.tmp.name));cls.root.mkdir(parents=True,exist_ok=True)
        cls.manifest=make_manifest(cls.weights,provenance={'kind':'RANDOM_INITIALIZATION_ENGINEERING_ONLY','evidence':'PCT_P2_A_20261114_01/weight_identity.json','seed':0})
        cls.manifest_path=cls.root/'model_manifest.json';cls.manifest_path.write_text(json.dumps(cls.manifest,indent=2)+'\n')
        cls.model=load_model(cls.manifest_path,cls.weights,expected_manifest_sha256=sha(cls.manifest_path))
        cls.rejections=[]

    def setUp(self):
        self.addCleanup(patch.stopall)
        def forbidden(*a,**k):raise AssertionError('P2B_FORBIDDEN_BUSINESS_OR_NETWORK')
        for method in ['connect','connect_ex']:patch.object(socket.socket,method,forbidden).start()
        # Do not invoke generators, order engines, monitoring/commit or LP even
        # if a selector implementation accidentally tries to route into them.
        from semantic_pallet_planner.jev_select import candidates,episode,transport,execution
        from semantic_pallet_planner.jev_select.stability import monitor
        for obj,name in [(candidates.CandidateProvider,'build'),(episode,'run_episode'),
                         (transport,'credential'),(execution,'commit_physical'),(monitor,'monitor_selected_action')]:
            patch.object(obj,name,forbidden).start()
        import scipy.optimize
        patch.object(scipy.optimize,'linprog',forbidden).start()

    def reject(self,name,fn):
        try:fn()
        except (ValueError,KeyError,TypeError,RuntimeError,OSError) as e:
            self.rejections.append({'name':name,'type':type(e).__name__,'error':str(e)});return
        self.fail('not rejected: '+name)

    def dump(self,name,value):
        (self.root/(name+'.json')).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

    def test_b23_exact_mapping_coordinates_and_symmetry(self):
        for symmetric in [False,True]:
            ctx,c=fixture(self.config,placed=True,symmetric=symmetric)
            e=encode_geometry(ctx);verify_candidates(e,c);r=e.data
            self.assertEqual(r['Lref_mm'],1000.)
            for i,row in enumerate(r['mapping']):
                src=c[i];self.assertEqual(row['candidate_id'],src['candidate_id']);self.assertEqual(row['candidate_digest'],digest(src))
                self.assertEqual(row['pose'],src['pose']);self.assertEqual(row['oriented_size_mm'],src['oriented_size_mm'])
                a=r['actual_leaf_corners_mm_float64'][i]
                np.testing.assert_allclose(inverse_corner(a,ctx.data['model_state']['container']),[src['pose'][k] for k in ['x_mm','y_mm','z_base_mm']],rtol=0,atol=1e-12)
                self.assertEqual(r['packed'][40+i][5],float(np.float32(.6)))
                self.assertNotEqual(row['actual_top_mm'],600.)
            self.assertEqual(r['actual_leaf_corners_mm_float64'][0][:3],[0.,0.,0.])
            self.assertEqual(r['actual_leaf_corners_mm_float64'][1][3:5],[1000.,800.])
            self.assertEqual(r['actual_leaf_corners_mm_float64'][2][2],40.75)
            self.dump('coordinates_'+str(symmetric),{'context':ctx.data,'candidates':c,'encoding':r})
        ctx,c=fixture(self.config);e=encode_geometry(ctx)
        self.assertTrue(e.data['valid_mask'][0]);self.assertEqual(e.data['packed'][0][:8],[0.]*8)
        self.assertEqual(e.data['packed'][56][:6],[float(np.float32(v/1000)) for v in [1,0,0,40.75,60.5,100.25]])
        self.dump('empty_pallet',{'context':ctx.data,'candidates':c,'encoding':e.data})

    def test_b24_batch_padding_routes_and_rejections(self):
        items=[fixture(self.config,count=n,placed=n==3) for n in [1,3,16]]
        es=[encode_geometry(ctx) for ctx,c in items]
        outputs=self.model.infer(es)
        singles=[self.model.infer([e])[0] for e in es]
        for e,output,single in zip(es,outputs,singles):
            self.assertEqual(output['leaf_index'],single['leaf_index'])
            np.testing.assert_allclose(output['probabilities'],single['probabilities'],rtol=1e-5,atol=1e-6)
            self.assertEqual(output['probabilities'][e.data['candidate_count']:],[0.]*(16-e.data['candidate_count']))
        self.dump('batch',{'encodings':[e.data for e in es],'outputs':outputs,'singles':singles})
        for n in [0,1,3]:
            ctx,c=fixture(self.config,count=n);selector=PCTGeoSelector(self.config,self.model);selector.bind_candidates(ctx,c)
            before=self.model.calls;selection=selector.select(ctx,decision_id='P2B_D0000')
            self.assertEqual(self.model.calls-before,1 if n>1 else 0)
            if not n:self.assertIsNone(selection);self.reject('empty_forward',lambda:self.model.infer([encode_geometry(ctx)]))
            else:self.dump('route_'+str(n),{'context':ctx.data,'candidates':c,'record':selector.last_record})
        ctx,c=fixture(self.config);e=encode_geometry(ctx)
        for index in [-1,3,16,1.0,True,None]:self.reject('invalid_index_'+str(index),lambda index=index:e.resolve(index))
        for label,alter in [('nan',lambda v:v['criteria']['C01']['pose'].update(x_mm=float('nan'))),('inf',lambda v:v['criteria']['C01']['pose'].update(x_mm=float('inf'))),
           ('bad_container',lambda v:v['model_state']['container'].update(width_mm=-1)),
           ('bounds',lambda v:v['criteria']['C01']['pose'].update(x_mm=-10000)),
           ('missing_mapping',lambda v:v['display_mapping'].pop('C01')),
           ('duplicate_id',lambda v:v['display_mapping']['C02'].update(candidate_id=v['display_mapping']['C01']['candidate_id'])),
           ('duplicate_digest',lambda v:v['display_mapping']['C02'].update(candidate_digest=v['display_mapping']['C01']['candidate_digest'])),
           ('wrong_orientation',lambda v:v['criteria']['C02'].update(oriented_size_mm=[100.25,60.5,40.75]))]:
            v=ctx.data;alter(v);self.reject(label,lambda v=v:encode_geometry(v))
        ctx17,c17=fixture(self.config,count=17);self.reject('leaf_overflow',lambda:encode_geometry(ctx17))
        v=ctx.data;v['model_state']['placed_objects']=[{'object_id':f'P{i}'} for i in range(41)]
        self.reject('placed_overflow',lambda:encode_geometry(v))
        for name,cc in [('missing_candidate',c[:-1]),('duplicate_candidate',[c[0],c[0],c[2]]),('changed_action',copy.deepcopy(c))]:
            if name=='changed_action':cc[0]['pose']['yaw_deg']=90
            self.reject(name,lambda cc=cc:verify_candidates(e,cc))
        p=torch.tensor([outputs[1]['probabilities']]);value=torch.zeros(1,1);idx=torch.tensor([[outputs[1]['leaf_index']]]);h=torch.zeros(1)
        for name,pp,vv,ii,hh in [('output_nan',p*float('nan'),value,idx,h),('value_inf',p,value+float('inf'),idx,h),
          ('output_shape',p[:,:15],value,idx,h),('index_shape',p,value,idx.squeeze(),h),('index_illegal',p,value,torch.tensor([[99]]),h),
          ('index_float',p,value,idx.float(),h),('padding_nonzero',torch.ones(1,16)/16,value,idx,h),('probability_sum',p/2,value,idx,h)]:
            self.reject(name,lambda pp=pp,vv=vv,ii=ii,hh=hh:checked_outputs([e],pp,vv,ii,hh))
        self.dump('rejections',self.rejections)


    def test_boundary40_display_order_and_identical_symmetric_leaves(self):
        ctx,c=fixture(self.config,placed=True,count=16);v=ctx.data
        first=v['model_state']['placed_objects'][0]
        v['model_state']['placed_objects']=[{**copy.deepcopy(first),'object_id':f'P{i:03d}'} for i in range(40)]
        ctx=rebind(v);e=encode_geometry(ctx)
        self.assertEqual(sum(e.data['valid_mask']),57)
        self.model.infer([e])
        v=ctx.data;v['display_mapping']=dict(reversed(list(v['display_mapping'].items())))
        other=rebind(v);reversed_encoding=encode_geometry(other)
        # Public Snapshot canonicalizes JSON object keys. Respect the order
        # actually supplied by context.data; raw public dictionaries retain theirs.
        self.assertEqual([r['display_label'] for r in reversed_encoding.data['mapping']],list(other.data['display_mapping']))
        raw_order=encode_geometry(v)
        self.assertEqual([r['display_label'] for r in raw_order.data['mapping']],list(v['display_mapping']))
        selector=PCTGeoSelector(self.config,self.model);selector.bind_candidates(ctx,c)
        changed=ctx.data;labels=list(changed['display_mapping']);a,b=labels[:2]
        changed['display_mapping'][a],changed['display_mapping'][b]=changed['display_mapping'][b],changed['display_mapping'][a]
        changed['criteria'][a],changed['criteria'][b]=changed['criteria'][b],changed['criteria'][a]
        self.reject('changed_presentation_after_binding',lambda:selector.select(rebind(changed),decision_id='P2B_D0000'))
        self.reject('pool_order_binding',lambda:selector.bind_candidates(ctx,list(reversed(c))))
        sym,sc=fixture(self.config,count=2,symmetric=True);v=sym.data
        sc[1]['pose']={**copy.deepcopy(sc[0]['pose']),'yaw_deg':90}
        v['criteria']['C02']['pose']=copy.deepcopy(sc[1]['pose']);v['display_mapping']['C02']['candidate_digest']=digest(sc[1])
        v['local_binding']['physical_digest']=v['local_binding']['selectable_digest']=digest(sc)
        sym=rebind(v);e=encode_geometry(sym);verify_candidates(e,sc)
        self.assertEqual(e.data['packed'][40],e.data['packed'][41])
        self.assertEqual(e.resolve(0)['pose']['yaw_deg'],0);self.assertEqual(e.resolve(1)['pose']['yaw_deg'],90)
        self.assertNotEqual(e.resolve(0)['candidate_id'],e.resolve(1)['candidate_id'])
        self.dump('capacity40_and_display_order',{'context':ctx.data,'encoding':encode_geometry(ctx).data,'reversed_context':other.data,'reversed_encoding':reversed_encoding.data})
        self.dump('identical_symmetric_leaves',{'context':sym.data,'candidates':sc,'encoding':e.data})
        for name in ['shape','nan','inf']:
            r=e.data
            if name=='shape':r['packed'].pop()
            else:r['packed'][0][0]=float(name)
            self.reject('packed_'+name,lambda r=r:self.model.infer([EncodedGeometry(r)]))
        self.dump('rejections',self.rejections)

    def test_b25_manifest_weight_identity_and_mutation(self):
        original=copy.deepcopy(self.manifest)
        changes={'version':lambda m:m.update(version='unknown'),'model_version':lambda m:m.update(model_version='pct_adapted_load_v1'),
          'features':lambda m:m['feature_contract'].update(dims=[11,12,6]),'structure':lambda m:m['architecture'].update(gat_layer_num=2),
          'runtime':lambda m:m['runtime'].update(dtype='torch.float64'),'core':lambda m:m['core_sha256'].update({'network_safety.py':'0'*64}),
          'weight_sha':lambda m:m.update(weights_sha256='0'*64),'extra':lambda m:m.update(extra=1),
          'parameter_key':lambda m:m['parameters'].pop(next(iter(m['parameters']))),
          'parameter_shape':lambda m:next(iter(m['parameters'].values())).update(shape=[1]),
          'parameter_dtype':lambda m:next(iter(m['parameters'].values())).update(dtype='torch.float64'),
          'parameter_digest':lambda m:next(iter(m['parameters'].values())).update(sha256='0'*64),
          'provenance':lambda m:m['provenance'].update(kind='PAPER_SCORE')}
        for name,change in changes.items():
            m=copy.deepcopy(original);change(m);p=self.root/('bad_manifest_'+name+'.json');p.write_text(json.dumps(m))
            self.reject('manifest_'+name,lambda p=p:load_model(p,self.weights,expected_manifest_sha256=sha(p)))
        self.reject('manifest_byte_sha',lambda:load_model(self.manifest_path,self.weights,expected_manifest_sha256='0'*64))
        raw=json.loads(self.weights.read_text())
        for name in ['keys','dtype','shape','nan','bool']:
            r=copy.deepcopy(raw);key=next(iter(r))
            if name=='keys':r.pop(key)
            elif name=='dtype':r[key]['dtype']='torch.float64'
            elif name=='shape':r[key]['shape']=[1]
            elif name=='bool':r[key]['values'][0][0]=True
            else:r[key]['values'][0][0]=float('nan')
            p=self.root/('bad_weights_'+name+'.json');p.write_text(json.dumps(r))
            m=copy.deepcopy(original);m['weights_sha256']=sha(p);mp=self.root/('bad_weight_manifest_'+name+'.json');mp.write_text(json.dumps(m))
            self.reject('weights_'+name,lambda p=p,mp=mp:load_model(mp,p,expected_manifest_sha256=sha(mp)))
        for kind in ['TRAINED','EXTERNAL']:
            m=copy.deepcopy(original);m['provenance']={'kind':kind,'evidence':'DECLARATION_ONLY_SYNTHETIC_METADATA_TEST','seed':None}
            p=self.root/('declared_'+kind+'.json');p.write_text(json.dumps(m));loaded=load_model(p,self.weights,expected_manifest_sha256=sha(p))
            self.assertEqual(loaded.manifest['provenance']['kind'],kind)
        ctx,c=fixture(self.config);e=encode_geometry(ctx);self.assertEqual(e.data,encode_geometry(ctx).data)
        a=self.model.infer([e]);b=self.model.infer([e]);self.assertEqual(a,b)
        fresh=load_model(self.manifest_path,self.weights,expected_manifest_sha256=sha(self.manifest_path));self.assertEqual(a,fresh.infer([e]))
        self.dump('repeatability',{'first':a,'repeat':b,'reload':fresh.infer([e])})
        with torch.no_grad():next(fresh._model.parameters()).add_(1)
        self.reject('loaded_weight_mutation',lambda:fresh.infer([e]))
        self.dump('rejections',self.rejections)


    def test_real_public_context_builder_single_step(self):
        from p2b_fixtures import SOURCE
        from semantic_pallet_planner.jev_select.context import ContextBuilder
        from semantic_pallet_planner.jev_select.contracts import CandidateBundle
        from semantic_pallet_planner.jev_select.packaging_runtime import no_policy
        from semantic_pallet_planner.jev_select.selector import bind_decision
        event=json.loads(SOURCE.read_text())['checkpoint']['pending_event']
        header=json.loads((SOURCE.parents[1]/'header.json').read_text())
        config=header['config'];req=event['observation'];bundle=CandidateBundle.from_dict(event['bundle'])
        ctx=ContextBuilder(config).build(req,bundle,no_policy(req))
        ctx=bind_decision(ctx,'P2B_PUBLIC_CONTEXT','P2B_PUBLIC_D0000',config=config)
        selector=PCTGeoSelector(config,self.model);selector.bind_candidates(ctx,bundle.data['physical_candidates'])
        answer=selector.select(ctx,decision_id='P2B_PUBLIC_D0000')
        record=selector.last_record
        self.assertEqual(answer.data['source'],'pct_local')
        self.assertEqual(record['exact_candidate']['candidate_id'],answer.data['selected_candidate_id'])
        self.dump('public_context_builder',{'source':str(SOURCE.relative_to(ROOT)),'observation':req,
            'bundle':bundle.data,'config':config,'context':ctx.data,'record':record,
            'scope':'single public context reconstruction + one selector call; no episode/resume/monitor/commit'})

    def test_saved_binding_and_public_only_geometry(self):
        ctx,c=fixture(self.config,placed=True);selector=PCTGeoSelector(self.config,self.model)
        selector.bind_candidates(ctx,c);selected=selector.select(ctx,decision_id='P2B_D0000');r=selector.last_record
        path=self.root/'saved_selection.json';save_selection(path,r);before=self.model.calls
        with patch.object(self.model,'infer',side_effect=AssertionError('saved selection must not infer')):
            reused=selector.reuse_saved(json.loads(path.read_text()),ctx,decision_id='P2B_D0000')
        self.assertEqual(selected.data,reused.data);self.assertEqual(before,self.model.calls)
        self.reject('saved_overwrite',lambda:save_selection(path,r))
        self.dump('saved_public_inputs',{'context':ctx.data,'config':self.config,'candidates':c,'selected':selected.data})
        for name,change in [('selection_id',lambda a:a['selection'].update(selected_candidate_id='wrong')),
            ('pose',lambda a:a['exact_candidate']['pose'].update(yaw_deg=90)),
            ('digest',lambda a:a.update(record_digest='0'*64)),('model',lambda a:a.update(model_manifest_sha256='0'*64)),
            ('encoding',lambda a:a['encoding']['packed'][40].__setitem__(0,999))]:
            bad=copy.deepcopy(r);change(bad)
            if name!='digest':bad['record_digest']=digest({k:v for k,v in bad.items() if k!='record_digest'})
            self.reject('saved_'+name,lambda bad=bad:validate_saved_selection(bad,ctx,c,config=self.config,expected_manifest_sha256=self.model.manifest_sha256,expected_weights_sha256=self.model.manifest['weights_sha256']))
        v=ctx.data;v['local_binding']['decision_id']='OTHER';self.reject('stale_decision',lambda:selector.select(rebind(v),decision_id='OTHER'))
        v=ctx.data;v['model_state']['available_objects'][0]['mass_kg']=999;v['model_state']['placed_objects'][0]['remaining_top_load_kg']=0
        v['criteria']['C01']['features']['geometry_score']=-999;v['criteria']['C01']['load_changes']=[]
        self.assertEqual(encode_geometry(ctx).data['feature_digest'],encode_geometry(v).data['feature_digest'])
        # Projection ignores unrelated metadata; real selector validates the closed
        # public context and rejects such keys before use. No task object supplied.
        v=ctx.data;v.update(future_items=['SECRET'],source_id='PRIVATE',witness='PRIVATE',monitor={'status':'UNSTABLE'})
        self.assertEqual(encode_geometry(ctx).data,encode_geometry(v).data)
        self.reject('unknown_private_context_fields',lambda:selector.bind_candidates(rebind(v),c))
        # Same geometry, different original actions for symmetric sizes: explicit
        # yaw/ID stay distinct, never inferred from dimensions.
        sym,sc=fixture(self.config,symmetric=True);se=encode_geometry(sym);self.assertNotEqual(se.resolve(0)['pose']['yaw_deg'],se.resolve(1)['pose']['yaw_deg'])
        from pct_baseline.execution import validate_selection
        self.reject('old_execution_rejects_pct_selection',lambda:validate_selection(ctx,selected,self.config))
        self.dump('rejections',self.rejections)


if __name__=='__main__':unittest.main()
