"""Explicit protocol fixtures; never evidence of VLM loading performance."""
import copy
import json


class OfflineTransport:
    offline_test_double = True

    def __init__(self, policy='first', script=None):
        if policy not in ('first', 'stop'):
            raise ValueError('unknown test-double policy')
        self.policy = policy
        self.script = list(script or [])
        self.calls = []

    def complete(self, body):
        self.calls.append(copy.deepcopy(body))
        req = json.loads(body['messages'][1]['content'][0]['text'])['public_input']
        response = {'request_id': req['request_id'], 'state_hash': req['state_hash'],
                    'action': 'STOP' if self.policy == 'stop' else 'PLACE',
                    'candidate_id': None if self.policy == 'stop' else req['candidates'][0]['candidate_id']}
        if self.script:
            entry = self.script.pop(0)
            if isinstance(entry, BaseException):
                raise entry
            if callable(entry):
                return entry(req, response)
            if entry != 'valid':
                return copy.deepcopy(entry)
        return response


def fixture_task(count=14, length=180, width=140, height=60, mass=1.):
    from .config import load
    return {'task_id': 'OFFLINE_FIXTURE', 'source_cluster_id': 'SYNTHETIC_PROTOCOL_FIXTURE',
            'source_order_key': 'NOT_A_RESEARCH_SOURCE', 'container': load()['container'],
            'items': [{'item_id': f'box_{i+1:02d}', 'dimensions_mm': {'length': length, 'width': width, 'height': height},
                       'mass_kg': mass, 'stackable': True, 'top_load_limit_kg_synthetic': 100.} for i in range(count)]}
