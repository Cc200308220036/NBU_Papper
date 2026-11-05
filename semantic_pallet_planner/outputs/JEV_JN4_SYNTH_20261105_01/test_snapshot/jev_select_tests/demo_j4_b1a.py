"""Small reviewable offline protocol demo; every artifact is fixture_only.

Run from planner with PYTHONPATH=src python -m
semantic_pallet_planner.jev_select.tests.demo_j4_b1a --output outputs/<new-id>
This development demo is excluded from the production wheel with tests/.
"""
import argparse
import shutil
from .unit.test_j4_b1a import card, history, query
from ..contracts import digest
from ..memory_retrieval import retrieve, card_text
from ..memory_store import indexed_snapshot, freeze_snapshot, load_snapshot
from ..ledger import write
from ..experiment import _new_output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    c=card()
    rows=[history(card_text(c),'fixture_match'),history('load: 负反馈 retained','fixture_chinese'),
        history('load '+'x'*1600,'fixture_oversize'),
        history('load','fixture_unknown',[{'field':'layout_height_mm','op':'gt','value':0}]),
        history('load','fixture_false',[{'field':'candidate_count','op':'gt','value':0}])]
    snapshot=indexed_snapshot([],cards=[c],fixture_only=True,raw_history=rows)
    out=_new_output(args.output);out.mkdir(parents=True)
    freeze_snapshot(snapshot,out/'snapshot')
    shutil.copytree(out/'snapshot',out/'migrated_snapshot')
    migrated=load_snapshot(out/'migrated_snapshot',digest(snapshot.data))
    q=query();write(out/'query.json',q)
    results={mode:retrieve(q,snapshot,mode) for mode in ('raw_history','cards')}
    for mode,result in results.items():
        assert result==retrieve(q,migrated,mode)==retrieve(q,snapshot,mode)
        write(out/f'{mode}_retrieval.json',result)
    report={'status':'PASS','fixture_only':True,'scope':'B1-A_OFFLINE_DEMO',
        'repeat_and_migration_identical':True,'snapshot_digest':digest(snapshot.data),
        'index_digest':snapshot.data['index_digest'],'query_digest':q['query_digest'],
        'selected_items':{mode:len(r['memories']) for mode,r in results.items()},
        'canonical_utf8_bytes':{mode:r['utf8_bytes'] for mode,r in results.items()},
        'model_api_calls':0,'production_training_evidence':False}
    write(out/'demo_report.json',report)
    print(report)


if __name__=='__main__':main()
