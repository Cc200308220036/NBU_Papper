"""Strict pinned JSON weights for pct_adapted_geo_v1; no download or training."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import torch
from .contracts import require, digest, sha
from .geo_encoding import FEATURE_CONTRACT
from .network_safety import PaddingSafeDRLGAT

MODEL_VERSION='pct_adapted_geo_v1'
ARCHITECTURE={'embedding_size':64,'hidden_size':128,'gat_layer_num':1,
              'internal_node_holder':40,'internal_node_length':6,'leaf_node_holder':16,
              'heads':1,'token_hidden':32,'graph_ff_hidden':128,'tanh_clipping':10}
RUNTIME={'dtype':'torch.float32','device':'cpu','normFactor':1,'eval_mode':True,
         'deterministic_selection':True,'deterministic_algorithms':True,'threads':1,
         'torch_version':'2.15.0','atol':1e-6,'rtol':1e-5}


def strict_read(path):
    def pairs(rows):
        value={}
        for k,v in rows:
            require(k not in value,'GEO_JSON_DUPLICATE_KEY');value[k]=v
        return value
    def invalid(v):raise ValueError('GEO_JSON_NONFINITE')
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=invalid)


def core_identity():
    root=Path(__file__).parent
    return {str(p.relative_to(root)):sha(p) for p in sorted([
        root/'network_safety.py',root/'geo_encoding.py',root/'geo_model.py',root/'geo_selector.py',*(root/'vendor/pct').glob('*.py')])}


def tensor_identity(t):
    return {'shape':list(t.shape),'dtype':str(t.dtype),
            'sha256':hashlib.sha256(t.detach().cpu().contiguous().numpy().tobytes()).hexdigest()}


def new_core():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(0)
        return PaddingSafeDRLGAT(SimpleNamespace(**ARCHITECTURE)).cpu().float().eval()


def make_manifest(weights_path,*,provenance):
    """Explicit metadata creation; provenance is a declaration, not certification."""
    raw=strict_read(weights_path);params=new_core().state_dict()
    require(set(raw)==set(params),'GEO_WEIGHT_KEYS')
    tensors={}
    for k,p in params.items():
        r=raw[k];require(set(r)=={'dtype','shape','values'},'GEO_WEIGHT_FIELDS')
        require(r['dtype']=='torch.float32' and digest(r['shape'])==digest(list(p.shape)),'GEO_WEIGHT_SHAPE_DTYPE')
        def numeric(v):
            return all(numeric(x) for x in v) if isinstance(v,list) else type(v) in (int,float)
        require(numeric(r['values']),'GEO_WEIGHT_VALUE_TYPE')
        t=torch.tensor(r['values'],dtype=torch.float64)
        require(list(t.shape)==list(p.shape) and bool(torch.isfinite(t).all()),'GEO_WEIGHT_VALUES')
        f=t.float();require(torch.equal(t,f.double()),'GEO_WEIGHT_NOT_FLOAT32_EXACT')
        tensors[k]=tensor_identity(f)
    return {'version':'pct_geo_model_manifest_v1','model_version':MODEL_VERSION,
        'feature_contract':copy.deepcopy(FEATURE_CONTRACT),'architecture':copy.deepcopy(ARCHITECTURE),
        'runtime':copy.deepcopy(RUNTIME),'core_sha256':core_identity(),
        'serialization':'p2a_tensor_json_v1','weights_sha256':sha(weights_path),
        'parameters':tensors,'key_mapping':'identity_upstream_DRL_GAT',
        'provenance':copy.deepcopy(provenance)}


class LoadedGeoModel:
    def __init__(self,model,manifest,manifest_sha256):
        self._model=model;self._manifest=copy.deepcopy(manifest);self.manifest_sha256=manifest_sha256
        self.calls=0

    @property
    def manifest(self):return copy.deepcopy(self._manifest)

    def check_identity(self):
        require(torch.__version__==RUNTIME['torch_version'] and torch.get_num_threads()==1
                and torch.are_deterministic_algorithms_enabled(),'GEO_RUNTIME_CHANGED')
        require(not self._model.training and not self._model.actor.training,'GEO_EVAL_MODE_CHANGED')
        require(core_identity()==self._manifest['core_sha256'],'GEO_CORE_CHANGED')
        require({k:tensor_identity(v) for k,v in self._model.state_dict().items()}==self._manifest['parameters'],'GEO_LOADED_WEIGHTS_CHANGED')

    def infer(self,encodings):
        require(isinstance(encodings,list) and encodings,'GEO_EMPTY_BATCH')
        require(all(not e.data['empty_pool'] for e in encodings),'GEO_EMPTY_POOL_NO_FORWARD')
        self.check_identity()
        x=torch.cat([e.tensor() for e in encodings],dim=0)
        with torch.inference_mode():
            _,indices,entropy,hidden,dist=self._model.actor(x,deterministic=True,normFactor=1,evaluate=True)
            values=self._model.critic(hidden)
            probabilities=dist.probs
        self.calls+=1
        return checked_outputs(encodings,probabilities,values,indices,entropy)


def checked_outputs(encodings,probabilities,values,indices,entropy):
    b=len(encodings)
    require(all(isinstance(t,torch.Tensor) for t in [probabilities,values,indices,entropy]),'GEO_OUTPUT_TYPE')
    require(probabilities.shape==(b,16) and values.shape==(b,1) and indices.shape==(b,1) and entropy.shape==(b,),'GEO_OUTPUT_SHAPE')
    require(probabilities.dtype==values.dtype==entropy.dtype==torch.float32 and indices.dtype==torch.int64,'GEO_OUTPUT_DTYPE')
    require(all(t.device.type=='cpu' and bool(torch.isfinite(t).all()) for t in [probabilities,values,indices,entropy]),'GEO_OUTPUT_NONFINITE')
    output=[]
    for e,p,v,i,h in zip(encodings,probabilities,values,indices,entropy):
        n=e.data['candidate_count'];require(n>0,'GEO_EMPTY_POOL_NO_FORWARD')
        require(bool((p>=0).all() and (p<=1).all()) and bool((p[n:]==0).all()),'GEO_PADDING_OR_PROBABILITY')
        require(torch.isclose(p.sum(),torch.tensor(1.),atol=1e-6,rtol=1e-5).item(),'GEO_PROBABILITY_SUM')
        index=int(i.item());e.resolve(index)
        require(index==int(torch.argmax(p).item()),'GEO_NOT_MAXIMUM_OR_TIE_RULE')
        output.append({'probabilities':p.tolist(),'value':float(v.item()),'leaf_index':index,'entropy':float(h.item())})
    return output


def load_model(manifest_path,weights_path,*,expected_manifest_sha256):
    require(type(expected_manifest_sha256) is str and sha(manifest_path)==expected_manifest_sha256,'GEO_MODEL_MANIFEST_SHA')
    m=strict_read(manifest_path)
    # Exact closed contract; no old Schema or protocol registration is modified.
    require(set(m)=={'version','model_version','feature_contract','architecture','runtime','core_sha256',
        'serialization','weights_sha256','parameters','key_mapping','provenance'},'GEO_MODEL_MANIFEST_FIELDS')
    require(m['version']=='pct_geo_model_manifest_v1' and m['model_version']==MODEL_VERSION,'GEO_MODEL_VERSION')
    require(digest(m['feature_contract'])==digest(FEATURE_CONTRACT),'GEO_FEATURE_CONTRACT')
    require(digest(m['architecture'])==digest(ARCHITECTURE),'GEO_ARCHITECTURE')
    require(digest(m['runtime'])==digest(RUNTIME) and torch.__version__==RUNTIME['torch_version'],'GEO_RUNTIME_CONTRACT')
    require(m['core_sha256']==core_identity(),'GEO_CORE_IDENTITY')
    require(m['serialization']=='p2a_tensor_json_v1' and m['key_mapping']=='identity_upstream_DRL_GAT','GEO_WEIGHT_FORMAT')
    p=m['provenance']
    require(isinstance(p,dict) and set(p)=={'kind','evidence','seed'},'GEO_PROVENANCE_FIELDS')
    require(p['kind'] in ('RANDOM_INITIALIZATION_ENGINEERING_ONLY','TRAINED','EXTERNAL') and
            isinstance(p['evidence'],str) and bool(p['evidence']) and
            (p['seed'] is None or type(p['seed']) is int),'GEO_PROVENANCE')
    require(sha(weights_path)==m['weights_sha256'],'GEO_WEIGHT_FILE_SHA')
    # Compare exact keys/shapes/dtypes/per-tensor hashes before strict loading.
    rebuilt=make_manifest(weights_path,provenance=p)
    require(m==rebuilt,'GEO_PARAMETER_MANIFEST')
    model=new_core();raw=strict_read(weights_path)
    state={k:torch.tensor(r['values'],dtype=torch.float32) for k,r in raw.items()}
    model.load_state_dict(state,strict=True)
    result=LoadedGeoModel(model,m,expected_manifest_sha256)
    result.check_identity()
    return result
