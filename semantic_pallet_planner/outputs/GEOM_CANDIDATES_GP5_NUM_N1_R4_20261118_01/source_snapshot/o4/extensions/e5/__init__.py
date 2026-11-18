"""E5 orchestration of frozen E2 semantics; E3 deferred, E4 out of scope."""
VERSION = 'o4_e5_090_development_v2'

import json
EXPECTED_CONFIG = json.loads('''{
  "version": "o4_e5_090_development_v2",
  "semantic_capability": "o4_e2_v1",
  "yaw_degrees": [0, 90],
  "e3_status": "DEFERRED",
  "e4_status": "OUT_OF_SCOPE",
  "source_orders": 12,
  "source_configurations": 2,
  "max_items_per_order": 12,
  "mixed_gold": 12,
  "construct_orders": 6,
  "per_object_top_k": 16,
  "joint_candidates_max": 48,
  "search": {"search_depth": 3, "beam_width": 8, "max_successor_evaluations": 256},
  "sampling_grid_mm": [0, 50, 100],
  "main_offline_episodes": 192,
  "construct_offline_episodes": 48,
  "oracle_repeats": 120,
  "oracle_restores": 120,
  "online_jobs": 240,
  "online_prefix_jobs": 20,
  "memoization": "exact_public_root_and_separate_posthoc_reference_copies_no_model_cache_v1",
  "search_counter_scope": "logical_work_on_exact_input_cache_hits",
  "new_api_attempts": 0
}
''')
