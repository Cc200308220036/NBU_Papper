"""Immutable memory snapshots and idempotent training exports. Never calls a model."""
from __future__ import annotations

import re
from pathlib import Path

from .contracts import MemorySnapshot, JevSelectError, canonical, digest, validate_schema
from .ledger import exclusive, read, write


def empty_snapshot() -> MemorySnapshot:
    return MemorySnapshot.from_dict({
        'version': 'jev_memory_snapshot_v1', 'corpus_digest': digest([]),
        'cards': [], 'raw_history': [], 'fixture_only': False,
        'retrieval_config': {'version': 'bm25_public_query_v1', 'k1': 1.2, 'b': .75}})


def validate_snapshot(snapshot: MemorySnapshot, expected_digest=None, *, remote=False):
    value = snapshot.data
    validate_schema('memory_snapshot', value)
    if expected_digest is not None and digest(value) != expected_digest:
        raise JevSelectError('memory_snapshot_changed')
    if remote and value['fixture_only']:
        raise JevSelectError('fixture_memory_in_remote_plan')
    ids = [c['card_id'] for c in value['cards']]
    if len(ids) != len(set(ids)):
        raise JevSelectError('duplicate_memory_card')
    histories = [h['history_id'] for h in value['raw_history']]
    if len(histories) != len(set(histories)):
        raise JevSelectError('duplicate_raw_history')
    from .memory_query import validate_gates
    for history in value['raw_history']:
        validate_gates(history.get('gates', []))
        if 'content_digest' in history and history['content_digest'] != digest(history['text']):
            raise JevSelectError('memory_history_content_changed')
        if 'utf8_bytes' in history and history['utf8_bytes'] != len(history['text'].encode('utf-8')):
            raise JevSelectError('memory_history_bytes_changed')
    for card in value['cards']:
        validate_gates(card.get('gates', []))
        if card.get('fixture_only') and not value['fixture_only']:
            raise JevSelectError('fixture_card_in_production_snapshot')
        # Identity excludes status/review, but includes all evidence and limitations.
        from .memory_validation import card_content
        content = card_content(card)
        if digest(content) != card['content_digest']:
            raise JevSelectError('memory_card_content_changed')
        if re.search(r'\b(?:C\d{2}|SCN_\d+|item_\d+)\b', canonical({k:card[k] for k in ('applicability','advice','observed_evidence','limitations_counterexamples')})):
            raise JevSelectError('memory_card_identifier_leak')
        if card['status'] == 'active':
            if card['version'] in ('jev_memory_card_v2','jev_memory_card_v3','jev_memory_card_v4'):
                from .memory_validation import eligible
                if not eligible(card): raise JevSelectError('memory_card_not_eligible_for_activation')
            groups = {e['source_group_id'] for e in card['evidence_refs']}
            if (len(groups) < 2 or card['knowledge_role'] == 'rule_restatement'
                    or card['semantic_review']['status'] != 'accepted'):
                raise JevSelectError('memory_card_not_eligible_for_activation')
    if sum(c['status'] == 'active' for c in value['cards']) > 64:
        raise JevSelectError('too_many_active_cards')
    if value['version'] == 'jev_memory_snapshot_v2':
        if value['history_preflight'].get('fixture_override',False) and not value['fixture_only']:
            raise JevSelectError('fixture_history_in_production_snapshot')
        from .memory_retrieval import build_index
        if value['index_digest'] != digest(value['index']) or value['index'] != build_index(value):
            raise JevSelectError('memory_index_changed')
    elif value['cards'] or value['raw_history']:
        raise JevSelectError('nonempty_memory_index_required')
    return value


def indexed_snapshot(exports, *, cards=(), fixture_only=False, raw_history=None):
    """Build a v2 offline snapshot; default B0 constructor remains byte-identical."""
    from .memory_export import build_raw_history, validate_export
    from .memory_retrieval import build_index
    exports = [validate_export(e) for e in exports]
    fixture_only = fixture_only or any(e.get('fixture_only', False) for e in exports)
    histories, report = build_raw_history(exports, projection='v2' if any(e['version']=='jev_episode_export_v2' for e in exports) else 'v1')
    if raw_history is not None:
        if not fixture_only: raise JevSelectError('history_override_requires_fixture')
        histories = list(raw_history)
        report = dict(report, fixture_override=True)
    value = empty_snapshot().data
    value.update(version='jev_memory_snapshot_v2', cards=list(cards), raw_history=histories,
                 fixture_only=fixture_only, corpus_digest=digest(sorted(digest(e) for e in exports)),
                 history_preflight=report)
    value['index'] = build_index(value)
    value['index_digest'] = digest(value['index'])
    snapshot = MemorySnapshot.from_dict(value)
    validate_snapshot(snapshot)
    return snapshot


def _validate_evidence(value, exports):
    """Resolve training provenance; semantic support/activation review remains B2."""
    if any(e.get('fixture_only',False) for e in exports) and not value['fixture_only']:
        raise JevSelectError('fixture_evidence_in_production_snapshot')
    by_digest = {digest(e):e for e in exports}
    for card in value['cards']:
        for ref in card['evidence_refs']:
            export = by_digest.get(ref['export_digest'])
            if (export is None or export['episode_id'] != ref['episode_id']
                    or export['source_group_id'] != ref['source_group_id']
                    or ref['decision_id'] not in {e['decision_id'] for e in export['events']}):
                if value['fixture_only'] and card.get('fixture_only'):
                    continue
                raise JevSelectError('memory_evidence_unresolved')
    if value['version'] == 'jev_memory_snapshot_v2' and not value['history_preflight'].get('fixture_override',False):
        from .memory_export import build_raw_history
        histories, report = build_raw_history(exports, projection='v2' if any(e['version']=='jev_episode_export_v2' for e in exports) else 'v1')
        if value['raw_history'] != histories or value['history_preflight'] != report:
            raise JevSelectError('memory_history_evidence_changed')


def freeze_snapshot(snapshot: MemorySnapshot, output, *, evidence_exports=(), artifacts=None) -> dict:
    """Create a content-addressed bundle. Existing directories are never overwritten."""
    value = validate_snapshot(snapshot)
    if any(c['version'] in ('jev_memory_card_v2','jev_memory_card_v3','jev_memory_card_v4') for c in value['cards']) and not artifacts:
        raise JevSelectError('generation_artifacts_required')
    from .memory_export import validate_export
    exports = sorted((validate_export(e) for e in evidence_exports), key=digest)
    if value['corpus_digest'] != digest([digest(e) for e in exports]):
        raise JevSelectError('memory_corpus_evidence_required')
    _validate_evidence(value, exports)
    from .experiment import _new_output
    root = _new_output(output)
    root.mkdir(parents=True)
    write(root / 'snapshot.json', value)
    for export in exports:
        write(root/'evidence'/f'{digest(export)}.json', export)
    if artifacts:
        for name, content in artifacts.items():
            target = root/'artifacts'/name
            if not target.resolve().is_relative_to((root/'artifacts').resolve()):
                raise JevSelectError('invalid_artifact_path')
            write(target, content)
    manifest = {'version': 'jev_memory_manifest_v1', 'snapshot_digest': digest(value),
                'files': {str(p.relative_to(root)): __import__('hashlib').sha256(p.read_bytes()).hexdigest()
                          for p in sorted(root.rglob('*.json'))}}
    write(root / 'memory_manifest.json', manifest)
    return manifest


def load_snapshot(path, expected_digest=None, *, remote=False) -> MemorySnapshot:
    import hashlib
    root = Path(path)
    manifest = read(root/'memory_manifest.json')
    if set(manifest) != {'version', 'snapshot_digest', 'files'} or manifest['version'] != 'jev_memory_manifest_v1':
        raise JevSelectError('invalid_memory_manifest')
    expected_names = {'snapshot.json', *(str(p.relative_to(root)) for p in (root/'evidence').glob('*.json'))}
    expected_names.update(str(p.relative_to(root)) for p in (root/'artifacts').rglob('*.json'))
    if set(manifest['files']) != expected_names:
        raise JevSelectError('memory_files_changed')
    for name, expected in manifest['files'].items():
        p = (root/name).resolve()
        if not p.is_relative_to(root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise JevSelectError('memory_files_changed')
    snapshot = MemorySnapshot.from_dict(read(root/'snapshot.json'))
    validate_snapshot(snapshot, manifest['snapshot_digest'], remote=remote)
    validate_snapshot(snapshot, expected_digest, remote=remote)
    from .memory_export import validate_export
    exports = [validate_export(read(p)) for p in sorted((root/'evidence').glob('*.json'))]
    if snapshot.data['corpus_digest'] != digest(sorted(digest(e) for e in exports)):
        raise JevSelectError('memory_corpus_changed')
    _validate_evidence(snapshot.data, exports)
    if any(c['version'] in ('jev_memory_card_v2','jev_memory_card_v3','jev_memory_card_v4') for c in snapshot.data['cards']) or (root/'artifacts').exists():
        from .memory_validation import validate_facts, validate_frozen_artifacts
        validate_frozen_artifacts(root, snapshot.data, exports)
    return snapshot


class MemoryStore:
    """Append-only export storage; a frozen bundle cannot be used as a mutable store."""
    def __init__(self, root):
        self.root = Path(root).resolve()

    def ingest(self, export):
        from .memory_export import validate_export
        value = validate_export(export)
        if (self.root/'memory_manifest.json').exists():
            raise JevSelectError('frozen_memory_is_readonly')
        self.root.mkdir(parents=True, exist_ok=True)
        with exclusive(self.root):
            identity = digest(value)
            path = self.root/'exports'/f'{identity}.json'
            if path.exists():
                if read(path) != value:
                    raise JevSelectError('training_export_changed')
                return {'status': 'ALREADY_INGESTED', 'export_digest': identity}
            # Same episode identity with different content is not a second training example.
            for previous in (self.root/'exports').glob('*.json'):
                old = read(previous)
                if old['episode_id'] == value['episode_id']:
                    raise JevSelectError('training_episode_identity_changed')
            write(path, value)
            return {'status': 'INGESTED', 'export_digest': identity}

    def freeze_snapshot(self, output, *, include_history=False):
        exports = [read(p) for p in sorted((self.root/'exports').glob('*.json'))]
        from .memory_export import validate_export
        for e in exports:
            validate_export(e)
        if include_history:
            return freeze_snapshot(indexed_snapshot(exports), output, evidence_exports=exports)
        value = empty_snapshot().data
        value['fixture_only'] = any(e.get('fixture_only',False) for e in exports)
        value['corpus_digest'] = digest(sorted(digest(e) for e in exports))
        # B0 carries the evidence corpus, but does not generate cards or retrieval text.
        return freeze_snapshot(MemorySnapshot.from_dict(value), output, evidence_exports=exports)
