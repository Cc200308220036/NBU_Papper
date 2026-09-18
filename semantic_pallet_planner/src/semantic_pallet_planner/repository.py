"""提供经过校验的只读数据集访问；隐藏标注只能通过显式方法获取。"""
import copy
import json
import re
from pathlib import Path
from jsonschema import Draft202012Validator
from .protocol import state_hash

BASE_SPLITS = ('train','validation','test_id','test_geometry_ood','test_semantic_ood')
ALL_SPLITS = (*BASE_SPLITS, 'test_language_ood')


class DatasetRepository:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._cache = {}
        self._validators = {}

    def _read(self, folder, identifier, schema, id_field):
        if not re.fullmatch(r'[A-Za-z0-9_]+', identifier):
            raise ValueError('invalid dataset identifier')
        key = (folder,identifier)
        if key not in self._cache:
            value = json.loads((self.root/folder/f'{identifier}.json').read_text())
            if schema not in self._validators:
                spec = json.loads((self.root/'schemas'/f'{schema}.schema.json').read_text())
                self._validators[schema] = Draft202012Validator(spec)
            self._validators[schema].validate(value)
            if value[id_field] != identifier:
                raise ValueError(f'file/ID mismatch: {identifier}')
            self._cache[key] = value
        return copy.deepcopy(self._cache[key])

    def get_scenario(self, identifier):
        value = self._read('tasks/scenarios',identifier,'scenario','scenario_id')
        ids = [x['item_id'] for x in value['items']]
        if len(set(ids)) != len(ids) or set(ids) != set(value['arrival_order']) or len(ids) != len(value['arrival_order']):
            raise ValueError('arrival_order does not identify every item exactly once')
        return value

    def get_candidate_set(self, identifier):
        value = self._read('candidates/candidate_sets',identifier,'candidate_set','candidate_set_id')
        ids = [c['candidate_id'] for c in value['candidates']]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate candidate IDs')
        return value

    def get_decision_case(self, identifier):
        case = self._read('tasks/decision_cases',identifier,'decision_case','decision_case_id')
        scenario = self.get_scenario(case['base_scenario_id'])
        cset = self.get_candidate_set(case['candidate_set_id'])
        if cset['scenario_id'] != scenario['scenario_id'] or cset['step_index'] != case['step_index']:
            raise ValueError('DC/CSET/scenario mismatch')
        if cset['physical_state_hash'] != state_hash(scenario['container'],case):
            raise ValueError('state hash mismatch')
        return case

    def get_oracle(self, identifier):
        value = self._read('annotations/oracle_candidate_scores',identifier,'oracle_annotation','decision_case_id')
        case = self.get_decision_case(identifier)
        cs = self.get_candidate_set(case['candidate_set_id'])
        ids = {c['candidate_id'] for c in cs['candidates']}
        scores = [c['candidate_id'] for c in value['candidate_evaluations']]
        if value['candidate_set_id'] != cs['candidate_set_id'] or set(scores) != ids or len(scores) != len(ids) or value['oracle_candidate_id'] not in ids:
            raise ValueError('Oracle/CSET mismatch')
        return value

    def get_rules(self, identifier):
        return self._read('annotations/ground_truth_rules',identifier,'ground_truth_rule','scenario_id')['ground_truth_rules']

    def split(self, name):
        return self._read('splits', name, 'split', 'split')

    def list_cases(self, split):
        if split == 'all':
            return sorted({i for s in ALL_SPLITS for i in self.split(s)['decision_case_ids']})
        return self.split(split)['decision_case_ids']

    def list_scenarios(self, split):
        if split in ('all','all_base'):
            return sorted({i for s in BASE_SPLITS for i in self.split(s)['scenario_ids']})
        return self.split(split)['scenario_ids']

    def split_for(self, identifier):
        for s in ALL_SPLITS:
            manifest = self.split(s)
            if identifier in manifest['scenario_ids'] or identifier in manifest['decision_case_ids']:
                return s
        raise ValueError(f'unknown split for {identifier}')

    def validate_links(self):
        for identifier in self.list_cases('all'):
            self.get_oracle(identifier)
        return {'cases':len(self.list_cases('all')), 'base_scenarios':len(self.list_scenarios('all_base'))}
