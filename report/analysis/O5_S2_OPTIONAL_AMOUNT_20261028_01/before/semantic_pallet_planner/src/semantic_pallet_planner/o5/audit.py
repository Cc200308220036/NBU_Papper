"""S0 read-only import, vendor-interface and historical-file protection evidence."""
import ast
import importlib
import importlib.metadata
import os
import subprocess
from pathlib import Path
import yaml
from .common import ROOT, atomic, digest, read, sha


def interfaces():
    imports = {}
    for name in ('o5.candidates', 'o5.episode', 'o4.extensions.e2.candidates', 'o4.extensions.e5.planning',
                 'evaluation.geometry_oracle', 'evaluation.state'):
        module = importlib.import_module('semantic_pallet_planner.'+name)
        imports[name] = {'path': module.__file__, 'sha256': sha(module.__file__)}
    vendor = ROOT/'ReMe-main'
    tree = {str(p.relative_to(vendor)): sha(p) for p in sorted(vendor.rglob('*'))
            if p.is_file() and not p.is_symlink() and not any(x in p.parts for x in ('.git', '__pycache__'))}
    config = yaml.safe_load((vendor/'reme/config/default.yaml').read_text())
    application = ast.parse((vendor/'reme/application.py').read_text())
    methods = [node.name for c in application.body if isinstance(c, ast.ClassDef) and c.name == 'Application'
               for node in c.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    versions = {}
    for name in ('reme-ai', 'agentscope', 'Pillow', 'jsonschema', 'numpy'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'NOT_INSTALLED'
    return {'schema_version': 'o5_s0_interfaces_v1',
            'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'git_status_current': subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True),
            'imports': imports, 'dependency_versions': versions,
            'candidate_adapter': {'entry': 'o4.extensions.e2.candidates.generate', 'regions': [],
                                  'ast_input': False, 'config_source': 'semantic_pallet_dataset_v1/configs/mvd_v0.1.json',
                                  'physical_top_load_kg': 100, 'buffer_capacity': 1,
                                  'business_observation_or_compiler_used': False,
                                  'state_owner': 'new O5 episode; physical checks/state update reused'},
            'reme': {'declared_version': '0.4.1.11', 'source_tree_digest': digest(tree), 'source_files': tree,
                     'application_methods': methods, 'runtime_initialized': False, 'new_api_attempts': 0,
                     'entry_mapping': {'ingest': 'proposed adapter over run_job(auto_memory,messages=...,session_id=...)',
                                       'consolidate': 'proposed adapter over auto_dream; extract + integrate per unit',
                                       'retrieve': 'BM25 search step/file_store.keyword_search; disable tool_context dedup for immutable queries',
                                       'freeze_restore': 'O5-owned card/index/config snapshots; not a vendor method'},
                     'default_background_jobs': {k: v['backend'] for k, v in config['jobs'].items()
                                                 if v.get('backend') in ('background', 'cron')},
                     'differences': ['auto_memory is Agent-based, not a single guaranteed HTTP attempt',
                                     'dream extract retries twice and integrate iterates units with its own retries',
                                     'Application startup starts all configured background/cron jobs',
                                     'S3 requires a minimal job allowlist config and underlying-model ledger/limits',
                                     'no ingest/consolidate/freeze/snapshot methods matching O5 semantic names',
                                     'S1 does not initialize ReMe or implement R0/M0'],
                     's3_status': 'ADAPTER_AND_CALL_BUDGET_DESIGN_REQUIRED_NOT_IMPLEMENTED'},
            'target_provider': {'status': 'NOT_VERIFIED_OFFLINE_SCOPE', 'cost': 'COST_NOT_FROZEN',
                                'real_image_transmission': 'NOT_RUN', 'seed_support': 'UNKNOWN'},
            'old_default': 'A remains default; explicit layout_v2/layout_v3 dispatch only',
            'new_api_attempts': 0}


def check_protection(baseline):
    data = read(baseline)
    changed = []
    for name, expected in data['files'].items():
        path = ROOT/name
        actual = ('symlink:'+os.readlink(path)) if path.is_symlink() else sha(path) if path.is_file() else 'MISSING'
        if actual != expected:
            changed.append(name)
    return {'schema_version': 'o5_protection_check_v1', 'status': 'PASS' if not changed else 'FAIL',
            'checked_files': len(data['files']), 'changed': changed,
            'head_before': data['head'], 'git_status_before': data['git_status_before'],
            'scope': 'all preexisting non-cache files; file hashes only, no historical replay', 'new_api_attempts': 0}
