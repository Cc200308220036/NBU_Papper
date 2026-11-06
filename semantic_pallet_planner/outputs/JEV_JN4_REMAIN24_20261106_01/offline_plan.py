"""Guarded static plan preparation/validation only. Never an execution wrapper."""
import sys
import socket
from pathlib import Path
from unittest.mock import patch
from semantic_pallet_planner.jev_select import transport
from semantic_pallet_planner.jev_select import packaging_exact_orders as exact
from semantic_pallet_planner.jev_select.ledger import write

if len(sys.argv)<2 or sys.argv[1] not in ('prepare-remaining','validate'):
    raise SystemExit('only prepare-remaining or validate is permitted')
counts={'network_attempts':0,'credential_accesses':0}
def no_network(*a,**kw):
    counts['network_attempts']+=1
    raise AssertionError('network blocked during static preparation')
def no_credential(*a,**kw):
    counts['credential_accesses']+=1
    raise AssertionError('credential blocked during static preparation')
original_open=Path.open
def guarded_open(path,*a,**kw):
    if path.name in ('typesafe_api_key.md','.env','.env.local'):
        return no_credential()
    return original_open(path,*a,**kw)
try:
    with patch.object(socket.socket,'connect',no_network), patch.object(socket.socket,'connect_ex',no_network), \
         patch.object(transport,'credential',no_credential),patch.object(Path,'open',guarded_open):
        exact.main()
finally:
    write(Path(__file__).parent/f'offline_guards_{sys.argv[1]}.json',counts)
