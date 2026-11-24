"""Draft text transformation only; no transport, credentials or execution entry."""
import copy
from pathlib import Path
ROOT=Path(__file__).parent
VERSION='gp6_mandatory_lexicographic_text_v1'

def full_instruction():
    return (ROOT/'base_selection_instructions.txt').read_text()+'\n\n'+(ROOT/'mandatory_instruction.txt').read_text().rstrip('\n')

def prepare_wire_body(base_body):
    original=(ROOT/'base_selection_instructions.txt').read_text()
    if base_body['questions']['next_action']['instructions']!=original:
        raise ValueError('EXPECTED_UNMODIFIED_BASE_INSTRUCTION')
    wire=copy.deepcopy(base_body)
    wire['questions']['next_action']['instructions']=full_instruction()
    return wire
