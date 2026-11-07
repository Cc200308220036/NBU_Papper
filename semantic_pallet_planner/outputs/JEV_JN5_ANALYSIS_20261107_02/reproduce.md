# Offline reproduction

Run from NBU_Papper root. Existing sealed directories refuse overwrite.

```bash
python3 semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_20261107_02/analyze.py --output semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01
python3 semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_20261107_02/plot.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01
python3 semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_20261107_02/verify.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01
python3 semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_20261107_02/deliver.py --input semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01 --report semantic_pallet_planner/outputs/JEV_JN5_ANALYSIS_REPRO_01/analysis_report.md
```

The scope file preserves the original post hoc freeze; dependency identity is in dependencies.json. Original saved records are required. No model or runtime replay. For sealing a reproduced copy, copy the original visual_review.json as prior review evidence or explicitly inspect regenerated figures; do not claim a new visual review automatically.
