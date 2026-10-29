"""Versioned transport profile; unknown provider/prices stay DRAFT, never guessed."""
import copy
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.parse import urlsplit
from .common import O5Error, canonical

TEMPLATE = {
    'schema_version': 'o5_s2_provider_profile_v1', 'provider': None, 'endpoint': None,
    'model': None, 'returned_model': None, 'snapshot_note': None, 'account_id': None,
    'credential_env': None, 'adapter': 'chat_completions_http_v1',
    'transport_verified': False, 'timeout_seconds': 60, 'temperature': 0,
    'seed': None, 'seed_support': 'UNKNOWN', 'image_detail': 'high',
    'input_limit': 12000, 'output_limit': 256, 'max_request_bytes': 30000000,
    'token_bound': {'algorithm': 'utf8_bytes_plus_image_bounds_v1',
                    'framing_tokens': None, 'per_image_tokens': None, 'evidence': None},
    'pricing': {'currency': None, 'input_per_million': None, 'output_per_million': None,
                'fixed_per_request': None, 'quantum': '0.000001', 'source': None,
                'verified_at': None, 'coverage': None},
    'limits': {'preflight_attempts': 8, 'pilot_attempts': 290,
               'preflight_amount': None, 'pilot_amount': None, 'total_amount': None},
}


def closed(value, exemplar):
    if not isinstance(value, dict) or set(value) != set(exemplar):
        raise O5Error('REMOTE_SCHEMA_ERROR')
    for k, v in exemplar.items():
        if isinstance(v, dict):
            closed(value[k], v)


def money(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        number = Decimal(value)
        if not number.is_finite() or number < 0:
            raise ValueError()
        return number
    except (InvalidOperation, ValueError):
        raise O5Error('INVALID_DECIMAL_AMOUNT') from None


def validate(profile):
    closed(profile, TEMPLATE)
    canonical(profile)
    if (profile['schema_version'] != TEMPLATE['schema_version'] or profile['adapter'] != TEMPLATE['adapter']
            or type(profile['transport_verified']) is not bool
            or type(profile['timeout_seconds']) not in (int, float) or not 0 < profile['timeout_seconds'] <= 600
            or profile['temperature'] != 0 or profile['image_detail'] != 'high'
            or profile['input_limit'] != 12000 or profile['output_limit'] != 256
            or profile['max_request_bytes'] != 30000000
            or profile['seed_support'] not in ('UNKNOWN', 'SUPPORTED', 'UNSUPPORTED')
            or (profile['seed'] is not None and type(profile['seed']) is not int)):
        raise O5Error('INVALID_REMOTE_PROFILE')
    for k in ('provider','endpoint','model','returned_model','snapshot_note','account_id','credential_env'):
        if profile[k] is not None and (not isinstance(profile[k], str) or not profile[k].strip()):
            raise O5Error('INVALID_REMOTE_PROFILE')
    if profile['endpoint'] is not None:
        u = urlsplit(profile['endpoint'])
        if u.scheme != 'https' or not u.netloc or u.username or u.password or u.query or u.fragment:
            raise O5Error('INVALID_ENDPOINT')
    if profile['credential_env'] is not None and not re.fullmatch(r'[A-Z][A-Z0-9_]*', profile['credential_env']):
        raise O5Error('INVALID_CREDENTIAL_REFERENCE')
    t = profile['token_bound']
    if t['algorithm'] != TEMPLATE['token_bound']['algorithm']:
        raise O5Error('UNSUPPORTED_TOKEN_BOUND')
    for k in ('framing_tokens','per_image_tokens'):
        if t[k] is not None and (type(t[k]) is not int or t[k] <= 0):
            raise O5Error('INVALID_TOKEN_BOUND')
    if t['evidence'] is not None and (not isinstance(t['evidence'],str) or not t['evidence'].strip()):
        raise O5Error('INVALID_TOKEN_BOUND')
    for k in ('currency','source','verified_at','coverage'):
        value=profile['pricing'][k]
        if value is not None and (not isinstance(value,str) or not value.strip()):
            raise O5Error('INVALID_PRICING_EVIDENCE')
    for k in ('input_per_million','output_per_million','fixed_per_request','quantum'):
        if profile['pricing'][k] is not None:
            money(profile['pricing'][k])
    if money(profile['pricing']['quantum']) <= 0:
        raise O5Error('INVALID_DECIMAL_AMOUNT')
    lim = profile['limits']
    if (type(lim['preflight_attempts']) is not int or not 1 <= lim['preflight_attempts'] <= 8
            or lim['pilot_attempts'] != 290):
        raise O5Error('INVALID_STAGE_ATTEMPT_LIMIT')
    for k in ('preflight_amount','pilot_amount','total_amount'):
        if lim[k] is not None:
            money(lim[k])
    return copy.deepcopy(profile)


def gaps(profile):
    validate(profile)
    missing = [k for k in ('provider','endpoint','model','returned_model','snapshot_note','account_id','credential_env')
               if profile[k] is None]
    if profile['seed_support'] == 'UNKNOWN':
        missing.append('seed_support')
    if profile['seed'] is not None and profile['seed_support'] != 'SUPPORTED':
        missing.append('seed_support_conflict')
    for group in ('token_bound','pricing','limits'):
        missing += [group+'.'+k for k,v in profile[group].items() if v is None]
    return missing


def require_cost(profile):
    missing = gaps(profile)
    if missing:
        raise O5Error('COST_NOT_FROZEN', ','.join(missing))
    if profile['pricing']['coverage'] != 'input_includes_images_all_fees_bounded':
        raise O5Error('UNBOUNDED_BILLING_ITEMS')
    return profile


def charge(profile, input_tokens, output_tokens):
    p = profile['pricing']
    for value in (input_tokens, output_tokens):
        if type(value) is not int or value < 0:
            raise O5Error('INVALID_USAGE')
    raw = ((Decimal(input_tokens)*money(p['input_per_million']) +
            Decimal(output_tokens)*money(p['output_per_million']))/Decimal(1000000)
           + money(p['fixed_per_request']))
    quantum = money(p['quantum'])
    return str((raw/quantum).to_integral_value(rounding=ROUND_CEILING)*quantum)
