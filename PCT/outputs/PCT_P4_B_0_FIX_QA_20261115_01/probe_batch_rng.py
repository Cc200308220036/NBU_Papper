"""Synthetic saved-prefix RNG probe. No order, model forward, LP or optimizer."""
import json
import random
import tempfile
from pathlib import Path
from pct_baseline.contracts import digest
from pct_baseline.p4b_storage import Store
from pct_baseline.p4b_training import BatchController

schedule=[{'attempt_index':i,'batch_id':i//8,'task_id':str(i),
           'policy_snapshot_id':'fixture-policy'} for i in range(2000)]
identity={'fixture':'batch-rng-only'}
random.seed(11)
uninterrupted=[random.random() for _ in range(8)]
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary)/'store'
    # Exactly the successful attempt record shape that BatchController reloads.
    # This models a process death after two durable attempts and before update.
    with Store(root,identity) as store:
        for i in range(2):
            store.append({'status':'COMPLETED','transitions':[{'draw':uninterrupted[i]}],
                          'slot_digest':digest(schedule[i]),'policy':'fixed'},key=f'attempt-{i:04d}')
    # train_model loads the preceding model/update snapshot and its batch-start
    # RNG, then BatchController skips the saved attempts without advancing RNG.
    random.seed(11)
    observed=[]
    with Store(root,identity) as store:
        controller=BatchController(store,schedule,'fixed')
        def collect(slot,policy):
            value=random.random();observed.append((slot['attempt_index'],value))
            return {'status':'COMPLETED','transitions':[{'draw':value}]}
        result=controller.batch(0,collect,lambda *_:'NO_OPTIMIZER_CALLBACK',lambda:'fixed')
    assert result=='NO_OPTIMIZER_CALLBACK'
    assert [i for i,_ in observed]==list(range(2,8))
    assert observed[0][1]==uninterrupted[0] and observed[0][1]!=uninterrupted[2]
    receipt={'status':'REPRODUCED_SYNTHETIC_RNG_CONTINUATION_MISMATCH',
             'saved_attempts':2,'new_synthetic_callbacks':6,
             'next_uninterrupted_draw':uninterrupted[2],
             'next_resumed_draw':observed[0][1],
             'mechanism':'prior snapshot RNG + skipped saved attempts without restoring post-attempt RNG',
             'scope':'real BatchController, synthetic collector and manually saved prefix; not production crash reproduction',
             'business_orders':0,'model_forwards':0,'optimizer_updates':0,'LP':0}
    target=Path(__file__).parent/'batch_rng_probe.json'
    target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt))
