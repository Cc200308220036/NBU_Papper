"""Single-step PCT selector and saved binding only; no execution admission."""
import copy
import time
from .contracts import digest, require, write_new
from .load_encoding import encode_load, verify_candidates
from .load_model import checked_outputs


def _pool_binding(context,candidates):
    b=context.data['local_binding']
    require(digest(candidates)==b['physical_digest']==b['selectable_digest'],'GEO_POOL_BINDING')


def _validate_context(context,config):
    from semantic_pallet_planner.jev_select.context import validate_context
    validate_context(context,config=config)
    require(context.data['version']=='jev_decision_context_b1_v1','GEO_CONTEXT_VERSION')
    require(context.data['request_body'] is None,'GEO_REMOTE_REQUEST_FORBIDDEN')
    require(context.data['model_state']['memories']==[],'GEO_MEMORIES_FORBIDDEN')


class PCTLoadSelector:
    """CandidateSelector protocol, explicitly NOT admitted to P1 order engines.

    `config` validates the public context carrier. It grants no PCT run permit.
    Exact candidates are bound in advance; only public geometry enters network.
    """
    def __init__(self,config,model):
        self.config=copy.deepcopy(config);self.model=model;self._bound=None
        self.last_record=None;self.calls=0

    def bind_candidates(self,context,candidates):
        _validate_context(context,self.config)
        _pool_binding(context,candidates)
        e=encode_load(context);verify_candidates(e,candidates)
        self._bound=(digest(context.data),copy.deepcopy(candidates),e.data['mapping_digest'])

    def select(self,context,*,decision_id):
        from semantic_pallet_planner.jev_select.contracts import validate_schema
        from semantic_pallet_planner.jev_select.selector import result,SelectionResult
        _validate_context(context,self.config)
        require(context.data['local_binding'].get('decision_id')==decision_id,'GEO_DECISION_CHANGED')
        require(self._bound is not None and self._bound[0]==digest(context.data),'GEO_UNBOUND_OR_STALE')
        e=encode_load(context)
        require(e.data['mapping_digest']==self._bound[2],'GEO_PRESENTATION_CHANGED')
        by_id=verify_candidates(e,self._bound[1])
        if e.data['empty_pool']:
            self.last_record=None
            return None  # public STOP_NO_PHYSICAL_CANDIDATE; no actor call
        started=time.perf_counter()
        if e.data['candidate_count']==1:
            row=e.resolve(0);output=None
            selection=result(context,status='singleton',source='singleton',label=row['display_label'])
        else:
            output=self.model.infer([e])[0];self.calls+=1
            row=e.resolve(output['leaf_index'])
            # Common result factory supplies the closed public result fields;
            # the final value is validated after adding real local inference.
            value=result(context,status='selected',source='local_baseline',label=row['display_label']).data
            value.update(source='pct_local',probabilities={r['display_label']:output['probabilities'][r['leaf_index']] for r in e.data['mapping']},
                confidence=output['probabilities'][row['leaf_index']],
                inference_receipt={'feature_digest':e.data['feature_digest'],
                    'weights_sha256':self.model.manifest['weights_sha256'],
                    'leaf_index':row['leaf_index'],'inference_s':time.perf_counter()-started})
            validate_schema('selection_result',value)
            selection=SelectionResult.from_dict(value)
        record={'version':'pct_load_single_step_v1','context_digest':digest(context.data),
                'local_binding_digest':digest(context.data['local_binding']),
                'model_manifest_sha256':self.model.manifest_sha256,
                'weights_sha256':self.model.manifest['weights_sha256'],
                'encoding':e.data,'output':output,'selected_mapping':row,
                'exact_candidate':by_id[row['candidate_id']],'selection':selection.data}
        record['record_digest']=digest(record)
        self.last_record=copy.deepcopy(record)
        return selection

    def reuse_saved(self,record,context,*,decision_id):
        require(context.data['local_binding'].get('decision_id')==decision_id,'GEO_DECISION_CHANGED')
        require(self._bound is not None and self._bound[0]==digest(context.data),'GEO_UNBOUND_OR_STALE')
        return validate_saved_selection(record,context,self._bound[1],config=self.config,
            expected_manifest_sha256=self.model.manifest_sha256,
            expected_weights_sha256=self.model.manifest['weights_sha256'])


def save_selection(path,record):
    """Exclusive single-step evidence file; no journal or recovery admission."""
    write_new(path,record)


def validate_saved_selection(record,context,candidates,*,config,expected_manifest_sha256,expected_weights_sha256):
    """Recheck saved facts without forward, candidate generation, LP or commit."""
    import torch
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    from semantic_pallet_planner.jev_select.selector import SelectionResult
    require(set(record)=={'version','context_digest','local_binding_digest','model_manifest_sha256',
        'weights_sha256','encoding','output','selected_mapping','exact_candidate','selection','record_digest'},'GEO_SAVED_FIELDS')
    require(record['version']=='pct_load_single_step_v1','GEO_SAVED_VERSION')
    require(record['record_digest']==digest({k:v for k,v in record.items() if k!='record_digest'}),'GEO_SAVED_DIGEST')
    require(record['model_manifest_sha256']==expected_manifest_sha256 and record['weights_sha256']==expected_weights_sha256,'GEO_SAVED_MODEL_IDENTITY')
    _validate_context(context,config)
    require(record['context_digest']==digest(context.data) and record['local_binding_digest']==digest(context.data['local_binding']),'GEO_SAVED_CONTEXT')
    _pool_binding(context,candidates)
    e=encode_load(context);by_id=verify_candidates(e,candidates)
    require(e.data==record['encoding'],'GEO_SAVED_ENCODING')
    output=record['output'];selection=record['selection'];validate_schema('selection_result',selection)
    if output is None:
        require(e.data['candidate_count']==1 and selection['status']=='singleton' and selection['source']=='singleton' and selection['inference_receipt'] is None,'GEO_SAVED_SINGLETON')
        row=e.resolve(0)
    else:
        require(set(output)=={'probabilities','value','leaf_index','entropy'} and type(output['leaf_index']) is int,'GEO_SAVED_OUTPUT_FIELDS')
        checked_outputs([e],torch.tensor([output['probabilities']],dtype=torch.float32),
            torch.tensor([[output['value']]],dtype=torch.float32),
            torch.tensor([[output['leaf_index']]],dtype=torch.int64),torch.tensor([output['entropy']],dtype=torch.float32))
        row=e.resolve(output['leaf_index']);receipt=selection['inference_receipt']
        require(selection['status']=='selected' and selection['source']=='pct_local' and
                receipt['feature_digest']==e.data['feature_digest'] and receipt['leaf_index']==row['leaf_index'] and
                receipt['weights_sha256']==expected_weights_sha256,'GEO_SAVED_INFERENCE')
        require(selection['probabilities']=={r['display_label']:output['probabilities'][r['leaf_index']] for r in e.data['mapping']} and
                selection['confidence']==output['probabilities'][row['leaf_index']],'GEO_SAVED_PROBABILITIES')
    require(selection['network_attempted'] is False and selection['attempt_ids']==[] and selection['error'] is None and
            selection['local_binding_digest']==record['local_binding_digest'] and
            selection['selected_display_id']==row['display_label'] and selection['selected_candidate_id']==row['candidate_id'],'GEO_SAVED_SELECTION')
    require(record['selected_mapping']==row and record['exact_candidate']==by_id[row['candidate_id']],'GEO_SAVED_EXACT_CANDIDATE')
    return SelectionResult.from_dict(copy.deepcopy(selection))
