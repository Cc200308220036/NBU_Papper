"""JN4-A source admission. Metadata only; no model, candidate or episode imports.

Absence from an incomplete historical register NEVER certifies unseen status.
The rules must be persisted before audit_sources is called.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
from .contracts import digest, JevSelectError
from .dataset_j4 import raw_items

VERSION = 'jev_source_admission_rule_v1'
HISTORY_NAMES = {'plan.json', 'input_snapshot.json', 'input_manifest.json',
                 'split_manifest.json', 'source_manifest.json', 'exposure_manifest.json',
                 'protocol.json', 'manifest.json', 'handoff.json'}
IDENTITY_FIELDS = {'source_order_key', 'original_source_order_key', 'source_order_id',
                   'original_source_order_id', 'source_key', 'source_order_keys'}
SKIP_FIELDS = {'candidate_new_sources', 'raw_source_identity_manifest', 'candidates',
               'source_manifest', 'source_sha256', 'source_file_manifest', 'source_files',
               'source', 'source_code', 'code_identity', 'code_sha256', 'files',
               'forbidden_historical_artifacts'}
SKIP_DIRS = {'code_snapshot', 'test_snapshot', '__pycache__', 'sources', 'jobs',
             'requests', 'responses', 'request_ledger', 'generation_requests', 'stages'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def require(ok, reason):
    if not ok:
        raise JevSelectError('source_admission_' + reason)


def fingerprints(order):
    ordered = []
    for row in raw_items(order):
        l,w,h = (round(float(row[k])) for k in ('length/mm','width/mm','height/mm'))
        ordered.append((min(l,w),max(l,w),h,round(float(row['weight/kg']),2)))
    return ordered, Counter(ordered)


def components(raw, alias_groups=()):
    """Conservative union of aliases, exact and 90% near duplicates.

    Inverted mechanical tokens avoid comparing disjoint orders. Near duplicate
    union is computed on original signatures, not on merged aggregate boxes.
    """
    parent = {k:k for k in raw}; edges=[]; first={}; rows={}; counts={}
    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]; k=parent[k]
        return k
    def union(a,b,reason):
        x,y=find(a),find(b)
        if x != y:
            parent[max(x,y)] = min(x,y)
            edges.append({'a':a,'b':b,'reason':reason})
    def link(token,k,reason):
        if token in first:union(k,first[token],reason)
        else:first[token]=k
    identity_owner={}
    for k,order in sorted(raw.items()):
        seq,cnt=fingerprints(order);rows[k]=seq;counts[k]=cnt
        ids={str(k)} | {str(v) for n,v in order.get('properties',{}).items() if n in ('id','order_nr')}
        for i in ids:
            link(('id',i),k,'original_identity');identity_owner.setdefault(i,k)
        link(('multiset',digest(sorted(seq))),k,'rotation_multiset')
    for group in alias_groups:
        members=sorted({identity_owner[x] for x in group if x in identity_owner})
        for k in members[1:]:union(members[0],k,'archived_alias_component')
    # Duplicate signatures can share one representative: all members already unioned.
    representatives={}
    for k in sorted(raw):representatives.setdefault(digest(sorted(rows[k])),k)
    inverted=defaultdict(list)
    for k in representatives.values():
        overlaps=defaultdict(int);n=len(rows[k])
        for token,count in counts[k].items():
            for other,old_count in inverted[token]:
                m=len(rows[other])
                if min(n,m) >= .9*max(n,m):overlaps[other]+=min(count,old_count)
        for other,intersection in overlaps.items():
            if intersection >= .9*min(n,len(rows[other])):
                union(k,other,'near_multiset_90pct')
        for token,count in counts[k].items():inverted[token].append((k,count))
    groups=defaultdict(list)
    for k in raw:groups[find(k)].append(k)
    descriptors={k:{'component':find(k),'item_count':len(rows[k]),
        'ordered_rotation_mass_digest':digest(rows[k]),'multiset_rotation_mass_digest':digest(sorted(rows[k]))}
        for k in sorted(raw)}
    return {k:sorted(v) for k,v in sorted(groups.items())},edges,descriptors


def historical_metadata(repo, exclude):
    repo=Path(repo); exclude=Path(exclude).resolve(); files=[]
    for base in (repo/'outputs',repo/'semantic_pallet_planner/outputs'):
        if not base.exists():continue
        for p in base.rglob('*.json'):
            if (p.name in HISTORY_NAMES and not p.resolve().is_relative_to(exclude)
                    and not SKIP_DIRS.intersection(p.relative_to(base).parts)):
                files.append(p)
    files += sorted((repo/'semantic_pallet_dataset_v1/annotations/ground_truth_rules').glob('*.json'))
    groups=repo/'semantic_pallet_dataset_v1/splits/group_manifest.json'
    if groups.is_file():files.append(groups)
    return sorted(set(files))


def exposure_records(files, repo):
    evidence=defaultdict(list);aliases=[];inventory={};parse_errors=[]
    def scan(v,path,loc='',inherited='UNKNOWN_EXPOSURE'):
        if isinstance(v,list):
            for i,x in enumerate(v):scan(x,path,f'{loc}/{i}',inherited)
        elif isinstance(v,dict):
            split=str(v.get('partition',v.get('split',''))).lower()
            status=inherited
            if split in ('train','dev','validation'):status='TRAIN_DEV_OR_REAL_RUN'
            elif split.startswith('test'):status='HISTORICAL_TEST' if '/annotations/' not in path else 'UNKNOWN_EXPOSURE'
            if v.get('exposed_training_only') is True:status='TRAIN_DEV_OR_REAL_RUN'
            # Legacy exposure hits are not automatically classified as training.
            ids=[]
            for field,x in v.items():
                if field in IDENTITY_FIELDS:
                    for identity in x if isinstance(x,list) else [x]:
                        if isinstance(identity,(str,int)) and str(identity).isdigit():
                            key=str(identity);ids.append(key)
                            evidence[key].append({'path':path,'pointer':f'{loc}/{field}','status':status,'declared_split':split,'usage_proof':'registered_metadata; not proof of actual model send'})
            if ids:aliases.append(ids)
            connected=v.get('connected_source_evidence',{})
            if connected:
                aliases.append(ids+connected.get('component_raw_keys',[])+connected.get('original_identities',[]))
            for field,x in v.items():
                if field not in IDENTITY_FIELDS and field not in SKIP_FIELDS:
                    scan(x,path,f'{loc}/{field}',status)
    for p in files:
        path=p.relative_to(repo).as_posix();inventory[path]=sha(p)
        try:scan(load(p),path)
        except (ValueError,TypeError) as exc:parse_errors.append({'path':path,'error':type(exc).__name__})
    # Explicit V1 physical/pair grouping also links transformed/subsequence variants.
    annotations={}
    for p in files:
        if '/annotations/ground_truth_rules/' in p.as_posix():
            value=load(p)
            annotations[value.get('scenario_id')]=[str(value[k]) for k in ('source_order_key','source_order_id') if k in value]
    manifest=Path(repo)/'semantic_pallet_dataset_v1/splits/group_manifest.json'
    if manifest in files:
        grouped=defaultdict(list)
        for row in load(manifest).get('groups',[]):
            for field in ('base_physical_id','pair_group_id'):
                if row.get(field):grouped[(field,row[field])].extend(annotations.get(row.get('scenario_id'),[]))
        aliases.extend(grouped.values())
    return dict(evidence),aliases,inventory,parse_errors


def audit_sources(raw, evidence, alias_groups=()):
    groups,edges,descriptors=components(raw,alias_groups)
    result=[]
    for component,members in groups.items():
        identities=set(members)
        for k in members:
            identities.update(str(v) for n,v in raw[k].get('properties',{}).items() if n in ('id','order_nr'))
        hits=[e for i in sorted(identities) for e in evidence.get(i,[])]
        statuses={e['status'] for e in hits}
        status=('TRAIN_DEV_OR_REAL_RUN' if 'TRAIN_DEV_OR_REAL_RUN' in statuses else
                'HISTORICAL_TEST' if 'HISTORICAL_TEST' in statuses else 'UNKNOWN_EXPOSURE')
        result.append({'component':component,'raw_keys':members,'identities':sorted(identities),
            'exposure_status':status,'evidence':hits,'strict_test_eligible':False,
            'assigned_split':'train' if status=='TRAIN_DEV_OR_REAL_RUN' else 'excluded',
            'reason':'component_has_training_or_development_exposure' if status=='TRAIN_DEV_OR_REAL_RUN' else
                     'historical_test_cannot_be_reused_as_strict_unseen' if status=='HISTORICAL_TEST' else
                     'no_closed_exposure_attestation; absence_of_hit_is_not_unseen',
            'evidence_statuses':sorted(statuses),
            'current_access':{'stage':'JN4-A','kind':'STATIC_SOURCE_AUDIT','model_or_policy_exposure':False}})
    return {'components':result,'edges':edges,'descriptors':descriptors,
            'counts':dict(Counter(x['exposure_status'] for x in result)),
            'strict_test_source_count':0,'scope':'local metadata only; external/deleted/unrecorded histories UNKNOWN'}


def validate_partition(rows):
    seen={}
    for row in rows:
        split=row['split'];component=row['component']
        require(component not in seen or seen[component]==split,'component_cross_split')
        seen[component]=split
        if split=='test':
            require(row['exposure_status']=='VERIFIED_UNSEEN' and row.get('closed_exposure_attestation'),
                    'unknown_or_exposed_test')
    return True
