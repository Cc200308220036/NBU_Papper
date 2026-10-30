"""Versioned V1 order adaptation. Source annotations supply provenance, never actions."""
from __future__ import annotations

import copy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
from collections import Counter, defaultdict

from semantic_pallet_planner.o4.fixtures import eq, rule
from semantic_pallet_planner.o4.extensions.data import spatial, region
from semantic_pallet_planner.o4.extensions.e2.data import relative, policy
from semantic_pallet_planner.o4.extensions.e2.compiler import render_policy
from semantic_pallet_planner.o4.extensions.e2.protocol import validate_policy

from .contracts import JevSelectError, canonical, digest


def business_spec():
    return json.loads(files('semantic_pallet_planner.jev_select').joinpath('configs','business_spec_v1.json').read_text())


def attribute_value(spec, article_id, attribute):
    return int(digest([spec['version'],spec['attribute_seed'],str(article_id),attribute])[:8],16)/2**32


def regions_for(container):
    length,width = container['length_mm'],container['width_mm']
    return [region('L',-length/2,length/4,-width/2,width/2),region('R',-length/4,length/2,-width/2,width/2),
            region('F',-length/2,length/2,-width/2,width/4),region('B',-length/2,length/2,-width/4,width/2)]


def build_business_policy(spec, group_id, configuration):
    food, cleaner = eq('cargo_category','food'),eq('cargo_category','household_cleaner')
    rules = [rule('label',limit='label',priority=spec['label_priority']),
             rule('no_top','no_top_load',eq('labels.no_top_load',True),priority=spec['no_top_priority'],overrides=['label']),
             rule('reinforced',target={'and':[eq('cargo_category','glassware'),eq('packaging.reinforced',True),eq('labels.no_top_load',False)]},
                  limit=spec['reinforced_limit_kg'],priority=spec['reinforced_priority'],overrides=['label']),
             rule('contact','forbidden_contact')]
    if configuration == 'B2':
        index = int(digest([spec['version'],group_id,'direction'])[:8],16)%4
        first,second = [('L','R'),('R','L'),('F','B'),('B','F')][index]
        rules += [spatial('food_region',food,first),spatial('cleaner_region',cleaner,second),
                  relative('relation',food,cleaner,spec['direction_mapping'][index],spec['relative_gap_mm'])]
    elif configuration != 'B1':
        raise JevSelectError('unknown_business_configuration')
    return validate_policy(policy(rules))


class DatasetOrderAdapter:
    def load(self, dataset_root, *, spec_config=None, split_manifest=None):
        root = Path(dataset_root).resolve()
        spec = business_spec() if spec_config is None else (json.loads(Path(spec_config).read_text()) if not isinstance(spec_config,dict) else copy.deepcopy(spec_config))
        if spec != business_spec():
            raise JevSelectError('business_spec_not_frozen', 'first version accepts the complete declared public specification')
        groups_path = root/'splits/group_manifest.json'
        if not groups_path.is_file(): raise JevSelectError('missing_dataset_group_manifest')
        all_groups = json.loads(groups_path.read_text())['groups']
        selected = sorted((g for g in all_groups if g['variant_id']=='canonical_instruction'),key=lambda g:g['scenario_id'])
        if not selected: raise JevSelectError('empty_dataset')
        source_files = {}; entries = []; excluded = []
        def read_source(path):
            if not path.resolve().is_relative_to(root):raise JevSelectError('dataset_path_escape')
            if not path.is_file(): raise JevSelectError('missing_dataset_file',str(path))
            raw = path.read_bytes(); source_files[str(path.relative_to(root))] = hashlib.sha256(raw).hexdigest()
            return json.loads(raw)
        read_source(groups_path)
        for g in all_groups:
            if g['variant_id'] != 'canonical_instruction':
                excluded.append({'scenario_id':g['scenario_id'],'reason':'same_source_language_or_buffer_variant','variant_id':g['variant_id']})
        for group in selected:
            sid = group['scenario_id']
            scenario = read_source(root/'tasks/scenarios'/f'{sid}.json')
            annotations = read_source(root/'annotations/ground_truth_rules'/f'{sid}.json')
            items = scenario['items']; arrival = scenario['arrival_order']
            ids = [o['item_id'] for o in items]
            if scenario['buffer_size'] != 1 or len(set(ids))!=len(ids) or len(set(arrival))!=len(arrival) or set(arrival)!=set(ids):
                raise JevSelectError('invalid_full_source_arrival',sid)
            articles = annotations['source_article_ids']
            if len(articles)!=len(items) or any(not isinstance(a,str) or not a for a in articles):
                raise JevSelectError('missing_article_identity',sid)
            entries.append({'group':group,'scenario':scenario,'provenance':annotations,
                            'articles':dict(zip(ids,articles))})
        # Connected source IDs, physical identities and pair variants form indivisible units.
        parent = {e['scenario']['scenario_id']:e['scenario']['scenario_id'] for e in entries}
        def find(x):
            while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
            return x
        def union(a,b):
            a,b = find(a),find(b)
            if a!=b: parent[max(a,b)]=min(a,b)
        first = {}
        for e in entries:
            sid=e['scenario']['scenario_id']; annotation=e['provenance'];g=e['group']
            identities={k:g[k] for k in ('base_physical_id','pair_group_id')}
            identities.update({k:str(annotation[k]) for k in ('source_order_key','source_order_id')})
            for key,value in identities.items():
                if (key,value) in first:union(sid,first[key,value])
                else:first[key,value]=sid
        components = defaultdict(list)
        for e in entries:components[find(e['scenario']['scenario_id'])].append(e)
        mapping = {}; audit_groups = []
        for component in components.values():
            ids = sorted(e['scenario']['scenario_id'] for e in component)
            partitions = {e['provenance']['split'] for e in component}
            if len(partitions)!=1:raise JevSelectError('source_group_cross_partition',','.join(ids))
            group_id = 'SG_'+digest(ids)[:16];partition=next(iter(partitions))
            for sid in ids:mapping[sid]={'source_group_id':group_id,'partition':partition}
            audit_groups.append({'source_group_id':group_id,'scenario_ids':ids,'partition':partition})
        split = {'version':'jev_grouped_split_v1','method':'preserve_original_after_connected_source_audit','seed':spec['attribute_seed'],
                 'groups':sorted(audit_groups,key=lambda g:g['source_group_id'])}
        if split_manifest is not None:
            supplied = json.loads(Path(split_manifest).read_text())
            if supplied != split:raise JevSelectError('split_manifest_mismatch')
        tasks = []; category_counts = Counter(); original_categories = Counter(); label_counts = Counter()
        for e in entries:
            scenario=e['scenario'];sid=scenario['scenario_id'];group=mapping[sid]
            originals={o['item_id']:o for o in scenario['items']}; attrs={}
            for oid,obj in originals.items():
                article=e['articles'][oid]; category=obj['product_category'];original_categories[category]+=1
                if category=='general':
                    choices=spec['cargo_category']['general_synthetic_choices']
                    category=choices[int(attribute_value(spec,article,'cargo_category')*len(choices))]
                elif category not in spec['cargo_category']['preserve']:
                    raise JevSelectError('undeclared_source_category',category)
                limit=spec['business_limits_kg'][int(attribute_value(spec,article,'business_top_load_kg')*len(spec['business_limits_kg']))]
                no_top=attribute_value(spec,article,'no_top_load')<spec['no_top_probability']
                reinforced=category=='glassware' and attribute_value(spec,article,'reinforced')<spec['reinforced_glass_probability']
                attrs[oid]={'object_id':oid,'cargo_category':category,'packaging':{'reinforced':reinforced},
                            'labels':{'no_top_load':no_top,'max_top_load_kg':limit},
                            'physical_top_load_limit_kg':obj['top_load_limit_kg_synthetic']}
                category_counts[category]+=1;label_counts['no_top']+=no_top;label_counts['reinforced']+=reinforced
                label_counts['business_no_top_physically_stackable']+=no_top and obj['stackable']
                label_counts['business_limit_lower_than_physical']+=limit<obj['top_load_limit_kg_synthetic']
            for configuration in spec['configurations']:
                ast=build_business_policy(spec,group['source_group_id'],configuration)
                task={'task_id':f'{sid}_{configuration}','source_kind':'dataset_orders_v1','source_order_key':group['source_group_id'],
                      'source_group_id':group['source_group_id'],'scenario_id':sid,'partition':group['partition'],
                      'business_configuration':configuration,'business_spec_source':'public_generated_v1','negative':False,
                      'feasibility_status':'unknown','container':copy.deepcopy(scenario['container']),
                      'items':[copy.deepcopy(originals[i]) for i in scenario['arrival_order']],
                      'attributes':copy.deepcopy(attrs),'regions':regions_for(scenario['container']),
                      'instruction_text':render_policy(ast),'reference_policy':copy.deepcopy(ast),
                      'public_spec':{'version':spec['version'],'configuration':configuration,'rules':copy.deepcopy(ast['rules']),
                                     'attribute_generation_digest':digest(spec)},
                      'provenance':{'original_source_order_key':str(e['provenance']['source_order_key']),
                                    'original_source_order_id':str(e['provenance']['source_order_id']),
                                    'base_physical_id':e['group']['base_physical_id'],'pair_group_id':e['group']['pair_group_id'],
                                    'original_instruction':copy.deepcopy(scenario['instruction']),
                                    'original_arrival_order':copy.deepcopy(scenario['arrival_order']),
                                    'article_ids':copy.deepcopy(e['articles']),'physical_source_digest':digest(scenario),
                                    'business_categories_synthetic':True}}
                tasks.append(task)
        tasks.sort(key=lambda t:(t['scenario_id'],t['business_configuration']))
        audit={'version':'jev_input_audit_v1','adapter':'dataset_orders_v1','status':'PASS',
               'included_base_scenarios':len(entries),'source_groups':len(components),'derived_tasks':len(tasks),
               'excluded_variants':excluded,'cross_partition_source_groups':0,
               'source_group_partitions':dict(Counter(g['partition'] for g in audit_groups)),
               'scenario_partitions':dict(Counter(e['provenance']['split'] for e in entries)),
               'original_category_counts':dict(original_categories),'synthetic_business_category_counts':dict(category_counts),
               'synthetic_label_counts':dict(label_counts),'business_spec_digest':digest(spec),'split_digest':digest(split),
               'source_file_manifest':source_files,'physical_attributes_changed':False,'arrival_order_truncated':False,
               'family_overlap_is_not_claimed_independent':True}
        return {'tasks':tasks,'business_spec':spec,'split_manifest':split,'input_audit':audit}
