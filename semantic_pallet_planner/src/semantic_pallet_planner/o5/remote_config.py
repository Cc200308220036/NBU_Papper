"""Versioned transport profiles with explicit optional or enforced amount budgets."""
import copy
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.parse import urlsplit
from .common import O5Error, canonical

TEMPLATE = {
    'schema_version': 'o5_s2_provider_profile_v2', 'amount_policy': 'unlimited',
    'provider': None, 'endpoint': None,
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
LEGACY_TEMPLATE = {k:copy.deepcopy(v) for k,v in TEMPLATE.items() if k!='amount_policy'}
LEGACY_TEMPLATE['schema_version']='o5_s2_provider_profile_v1'


TEXT_PROFILE_VERSION = 'o5_direct_text_provider_profile_v1'
TEXT_TEMPLATE = copy.deepcopy(TEMPLATE)
TEXT_TEMPLATE['schema_version'] = TEXT_PROFILE_VERSION
del TEXT_TEMPLATE['image_detail']
TEXT_TEMPLATE['token_bound'] = {'algorithm': 'utf8_bytes_plus_framing_v1',
                                 'framing_tokens': None, 'evidence': None}


def request_version(profile):
    return ('o5_direct_text_request_v1' if profile['schema_version'] == TEXT_PROFILE_VERSION
            else 'o5_decision_request_v1')


def amount_policy(profile):
    # Old profiles remain capped; missing prices must never silently disable a legacy cap.
    return 'capped' if profile['schema_version']=='o5_s2_provider_profile_v1' else profile['amount_policy']


def pricing_ready(profile):
    p=profile.get('pricing',{})
    return (set(TEMPLATE['pricing'])<=set(p) and all(v is not None for v in p.values())
            and p['coverage']=='input_includes_images_all_fees_bounded')


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
    profile=copy.deepcopy(profile)
    if isinstance(profile,dict) and profile.get('schema_version') in (TEMPLATE['schema_version'],TEXT_PROFILE_VERSION):
        if 'pricing' not in profile:
            profile['pricing']=copy.deepcopy(TEMPLATE['pricing'])
        elif isinstance(profile['pricing'],dict):
            profile['pricing']={**TEMPLATE['pricing'],**profile['pricing']}
        if isinstance(profile.get('limits'),dict):
            for k in ('preflight_amount','pilot_amount','total_amount'):
                profile['limits'].setdefault(k,None)
    exemplar=LEGACY_TEMPLATE if isinstance(profile,dict) and profile.get('schema_version')==LEGACY_TEMPLATE['schema_version'] else TEMPLATE
    if isinstance(profile,dict) and profile.get('schema_version') == TEXT_PROFILE_VERSION:
        exemplar = TEXT_TEMPLATE
    closed(profile, exemplar)
    canonical(profile)
    if (profile['schema_version'] != exemplar['schema_version'] or profile['adapter'] not in (TEMPLATE['adapter'],'deepseek_flash_chat_v1')
            or amount_policy(profile) not in ('unlimited','capped')
            or type(profile['transport_verified']) is not bool
            or type(profile['timeout_seconds']) not in (int, float) or not 0 < profile['timeout_seconds'] <= 600
            or profile['temperature'] != 0 or (profile.get('image_detail', 'high') != 'high')
            or profile['input_limit'] != 12000 or profile['output_limit'] != 256
            or profile['max_request_bytes'] != 30000000
            or profile['seed_support'] not in ('UNKNOWN', 'SUPPORTED', 'UNSUPPORTED')
            or (profile['seed'] is not None and type(profile['seed']) is not int)):
        raise O5Error('INVALID_REMOTE_PROFILE')
    if profile['adapter']=='deepseek_flash_chat_v1' and (
            profile['endpoint']!='https://api.deepseek.com/chat/completions'
            or profile['model']!='deepseek-flash' or profile['seed'] is not None):
        raise O5Error('INVALID_DEEPSEEK_FLASH_PROFILE')
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
    if t['algorithm'] != exemplar['token_bound']['algorithm']:
        raise O5Error('UNSUPPORTED_TOKEN_BOUND')
    for k in (set(exemplar['token_bound']) - {'algorithm','evidence'}):
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
    if profile['pricing']['quantum'] is not None and money(profile['pricing']['quantum']) <= 0:
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
    profile=validate(profile)
    missing = [k for k in ('provider','endpoint','model','returned_model','snapshot_note','account_id','credential_env')
               if profile[k] is None]
    if profile['seed_support'] == 'UNKNOWN':
        missing.append('seed_support')
    if profile['seed'] is not None and profile['seed_support'] != 'SUPPORTED':
        missing.append('seed_support_conflict')
    for group in ('token_bound',):
        missing += [group+'.'+k for k,v in profile[group].items() if v is None]
    if amount_policy(profile)=='capped':
        for group in ('pricing','limits'):
            missing += [group+'.'+k for k,v in profile[group].items() if v is None]
    return missing


def require_cost(profile):
    """Compatibility name: require runtime inputs, and monetary inputs only in capped mode."""
    profile=validate(profile)
    missing = gaps(profile)
    if missing:
        code='COST_NOT_FROZEN' if amount_policy(profile)=='capped' else 'REMOTE_PROFILE_INCOMPLETE'
        raise O5Error(code, ','.join(missing))
    if amount_policy(profile)=='capped' and profile['pricing']['coverage'] != 'input_includes_images_all_fees_bounded':
        raise O5Error('UNBOUNDED_BILLING_ITEMS')
    return profile


def charge(profile, input_tokens, output_tokens):
    profile=validate(profile)
    p = profile['pricing']
    for value in (input_tokens, output_tokens):
        if type(value) is not int or value < 0:
            raise O5Error('INVALID_USAGE')
    if not pricing_ready(profile):
        return None  # Unknown price is unknown cost, never zero or a fabricated currency.
    raw = ((Decimal(input_tokens)*money(p['input_per_million']) +
            Decimal(output_tokens)*money(p['output_per_million']))/Decimal(1000000)
           + money(p['fixed_per_request']))
    quantum = money(p['quantum'])
    return str((raw/quantum).to_integral_value(rounding=ROUND_CEILING)*quantum)
