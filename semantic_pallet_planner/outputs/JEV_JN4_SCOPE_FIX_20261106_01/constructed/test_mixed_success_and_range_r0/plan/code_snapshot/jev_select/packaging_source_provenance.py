"""Positive source admission from scoped, authenticated provenance statements.

A signature authenticates a named issuer's statement, not objective omniscience.
Trust roots are an independent caller-frozen policy, never taken from evidence.
No custodian signature/complete scope => UNKNOWN, never unseen by absence.
"""
from datetime import datetime
from pathlib import Path
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from .contracts import canonical,digest,validate_schema
from .packaging_source_audit import require,sha,load
DOMAINS=['model_requests','policy_development','training','memory_build','historical_testing','aliases_variants_forks']
VERSION='jev_source_provenance_v1'


def component_identity(component,raw_manifest,raw_order_digests=None):
    return {'component':component['component'],'raw_keys':sorted(component['raw_keys']),
            'raw_manifest_sha256':raw_manifest,'raw_order_digests':raw_order_digests or {},'identities':sorted(component['identities'])}


def adjudicate(identity,statement,policy,*,evidence_root,observed_uses=(),as_of):
    validate_schema('source_trust_policy_v1',policy)
    gaps=[];uses=list(observed_uses);issuer=None
    if set(identity.get('raw_order_digests',{}))!=set(identity['raw_keys']):gaps.append('per_raw_order_identity_digests_incomplete')
    if statement is None:
        gaps=['missing_signed_provenance','missing_authoritative_coverage','missing_origin_and_usage_records','missing_component_review']
    else:
        validate_schema('source_provenance_v1',statement)
        body=statement['body'];issuer=body['issuer']
        require(body['source_identity']==identity,'provenance_component_identity_changed')
        require(body['body_digest']==digest({k:v for k,v in body.items() if k!='body_digest'}),'provenance_body_tampered')
        fixture=body['fixture_only']
        require(not fixture or policy['fixture_only'],'fixture_proof_as_real')
        trust=policy['issuers'].get(issuer)
        if trust is None:gaps.append('issuer_not_in_independently_frozen_trust_roots')
        else:
            try:
                Ed25519PublicKey.from_public_bytes(bytes.fromhex(trust['public_key_hex'])).verify(
                    base64.b64decode(statement['signature_b64'],validate=True),canonical(body).encode())
            except (InvalidSignature,ValueError):require(False,'provenance_signature_invalid')
            if trust['authority_scope']!='complete_source_lifecycle':gaps.append('issuer_authority_scope_incomplete')
        require(policy['fixture_only'] or not fixture,'fixture_proof_as_real')
        coverage=body['coverage'];origin=body['origin']
        if set(coverage['domains'])!=set(DOMAINS):gaps.append('history_domains_incomplete')
        try:
            created=datetime.fromisoformat(origin['created_at']);start=datetime.fromisoformat(coverage['from']);end=datetime.fromisoformat(coverage['through']);cut=datetime.fromisoformat(as_of)
            if start>created or end<cut:gaps.append('lifecycle_time_coverage_incomplete')
        except (ValueError,TypeError):gaps.append('invalid_time_coverage')
        if not coverage['closed_world']:gaps.append('external_or_unrecorded_history_not_closed')
        gaps.extend('declared_unknown:'+x for x in body['unknowns'])
        if body['review']['conclusion']!='COMPLETE':gaps.append('component_review_incomplete')
        if body['review']['component_identity_digest']!=digest(identity):gaps.append('component_alias_review_missing')
        references=body['evidence_files'];root=Path(evidence_root).resolve()
        for n,h in references.items():
            p=(root/n).resolve();require(p.is_relative_to(root) and p.suffix=='.json','unsafe_provenance_reference')
            require(p.is_file() and sha(p)==h,'provenance_evidence_missing_or_tampered')
        if not references or origin['evidence_file'] not in references:gaps.append('origin_evidence_not_bound')
        for event in body['uses']:
            if event['evidence_file'] not in references:gaps.append('usage_evidence_not_bound:'+event['id'])
            uses.append(event['kind'])
        if body['review']['evidence_file'] not in references:gaps.append('review_evidence_not_bound')
        # A lifecycle declaration has its own evidence even when the usage list is empty.
        if coverage['evidence_file'] not in references:gaps.append('coverage_evidence_not_bound')
    polluted=any(x in ('model_requests','policy_development','training','memory_build') for x in uses)
    tested='historical_testing' in uses
    status='CONTAMINATED' if polluted else 'HISTORICAL_TEST' if tested else 'UNKNOWN_EXPOSURE' if gaps else 'VERIFIED_UNSEEN'
    result={'version':'jev_source_admission_v1','source_identity':identity,'status':status,
       'strict_test_eligible':status=='VERIFIED_UNSEEN','gaps':sorted(set(gaps)),
       'usage_kinds':sorted(set(uses)),'issuer':issuer,'policy_digest':digest(policy),
       'statement_digest':digest(statement),'as_of':as_of,'fixture_only':policy['fixture_only'],
       'review_type':'deterministic signature/scope/evidence validation; no fabricated human approval',
       'limitations':'issuer statement and trust policy are assumptions; audit access recorded separately; no absence-of-hit inference'}
    result['admission_digest']=digest(result);return result


def audit_admissions(components,raw_manifest,statements,policy,*,evidence_root,as_of,raw_orders=None):
    records=[]
    for c in components:
        identity=component_identity(c,raw_manifest,{k:digest(raw_orders[k]) for k in c['raw_keys']} if raw_orders is not None else None)
        observed=['policy_development'] if c['exposure_status']=='TRAIN_DEV_OR_REAL_RUN' else ['historical_testing'] if c['exposure_status']=='HISTORICAL_TEST' else []
        records.append(adjudicate(identity,statements.get(c['component']),policy,evidence_root=evidence_root,observed_uses=observed,as_of=as_of))
    return {'version':'jev_source_admission_batch_v1','records':records,
      'eligible_components':[x['source_identity']['component'] for x in records if x['strict_test_eligible']],
      'source_count':sum(x['strict_test_eligible'] for x in records),'policy_digest':digest(policy)}


def main():
    import argparse
    from .ledger import write
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',required=True);parser.add_argument('--audit-sha256',required=True)
    parser.add_argument('--raw',required=True);parser.add_argument('--policy',required=True)
    parser.add_argument('--policy-digest',required=True);parser.add_argument('--proofs',required=True)
    parser.add_argument('--as-of',required=True);parser.add_argument('--output',required=True)
    a=parser.parse_args();require(sha(a.audit)==a.audit_sha256,'admission_audit_identity')
    policy=load(a.policy);require(digest(policy)==a.policy_digest,'admission_trust_root_identity')
    raw=load(a.raw);raw_sha=sha(a.raw);statements={}
    for f in sorted(Path(a.proofs).glob('*/statement.json')):
        statements[f.parent.name]=load(f)
    # Each component has its own evidence root. Missing statements still yield a
    # traceable UNKNOWN record; available proofs are verified separately.
    components=load(a.audit)['components'];records=[]
    for c in components:
        identity=component_identity(c,raw_sha,{k:digest(raw[k]) for k in c['raw_keys']})
        observed=['policy_development'] if c['exposure_status']=='TRAIN_DEV_OR_REAL_RUN' else ['historical_testing'] if c['exposure_status']=='HISTORICAL_TEST' else []
        records.append(adjudicate(identity,statements.get(c['component']),policy,evidence_root=Path(a.proofs)/c['component'],observed_uses=observed,as_of=a.as_of))
    out=Path(a.output);require(not out.exists(),'admission_output_exists')
    write(out,{'version':'jev_source_admission_batch_v1','records':records,'eligible_components':[x['source_identity']['component'] for x in records if x['strict_test_eligible']],
      'source_count':sum(x['strict_test_eligible'] for x in records),'policy_digest':digest(policy),'source_audit_sha256':sha(a.audit),'raw_sha256':raw_sha})
    print(canonical({'sources':sum(x['strict_test_eligible'] for x in records),'status':'READY' if any(x['strict_test_eligible'] for x in records) else 'NOT_READY'}))

if __name__=='__main__':main()
