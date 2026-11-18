# GP5 NUM N1 R1 schema repair and bounded validation

PARTIAL / STOPPED. See the Chinese report, handoff.json, checks.json and validation_outcomes.json.

Only the erroneous item-ID pattern was removed. Three pure Schema tests pass; all 13 candidate-ID patterns remain. C6 and pure X5 pass. First new E2 K02_INT job completed both boxes with 2 TEST_DOUBLE monitors and 2 commits. The harness then failed its own dictionary.values axis-order assertion. E/run.json is production status; E_results.json is the raw failing suite status. Both are preserved.

Old failed E monitoring1 + new E monitoring2 = cumulative3 (limit17). Remaining7 E, R, runtime X/H and administrator task tests are NOT_RUN. No implicit rerun of run_bounded_validation.py; its one-shot marker is retained. The snapshot-fork code was never reached or executed.

inspect_saved_delivery.py reads saved facts and frozen identities only, writes this new package analysis, imports no production modules and never replays an order. Passing that checker is not completion of the bounded suite. Original failed package and QA remain unchanged. No commit/push or next-stage authorization.
