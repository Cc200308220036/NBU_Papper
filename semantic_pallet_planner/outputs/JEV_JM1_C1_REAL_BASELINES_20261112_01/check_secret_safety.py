"""Check authorized artifact bytes for loaded secret; never prints/persists the secret."""
from pathlib import Path
from semantic_pallet_planner.jev_select.transport import credential
from semantic_pallet_planner.jev_select.ledger import read,write
out=Path(__file__).resolve().parent
freeze=read('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/formal_freeze.json')
secret=credential('TYPESAFE_API_KEY','typesafe_api_key.md').encode()
files=[p for p in out.rglob('*') if p.is_file()]+[p for p in Path(freeze['runtime_root']).rglob('*') if p.is_file()]
hit=any(secret in p.read_bytes() for p in files)
del secret
write(out/'credential_safety.json',dict(version='jm_c1_credential_safety_v1',checked_artifact_files=len(files),credential_value_in_artifacts=hit,status='FAIL' if hit else 'PASS',credential_source='existing typesafe_api_key.md',secret_copied=False,secret_printed=False,secret_fingerprint_saved=False))
assert not hit,'SECRET_IN_ARTIFACTS_STOP_PUBLICATION'
print('PASS_NO_CREDENTIAL_VALUE_IN_ARTIFACTS')
