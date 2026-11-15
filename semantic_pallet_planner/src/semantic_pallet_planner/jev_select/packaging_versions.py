"""Explicit registration for the independently versioned exact-pose protocol."""
EXACT_VERSION='jev_packaging_synthetic_v12'
EXACT_CONTEXT='jev_decision_context_v12'
EXACT_BUNDLE='jev_candidate_bundle_v12'
EXACT_PLAN='jev_synthetic_supplement_plan_v2'
EXACT_RUN='jev_synthetic_supplement_run_v2'
REMAINDER_PLAN='jev_synthetic_remainder_plan_v3'

# JM1-A1 is an independent fork/forced-selection protocol over saved envelopes.
JM_FORK_VERSION='jev_jm_fork_binding_v1'
JM_FORK_PROTOCOLS={JM_FORK_VERSION: 'packaging_jev_forks'}

# A2 has a separate execution wrapper; A1 binding and stop route stay intact.
JM_CONTINUATION_VERSION='jev_jm_continuation_v1'
JM_CONTINUATION_PROTOCOLS={JM_CONTINUATION_VERSION: 'packaging_jev_continuation'}

# A3 recovery/repeats are independent; old execution schemas remain closed.
JM_RECOVERY_VERSION='jev_jm_recovery_v1'
JM_RECOVERY_PROTOCOLS={JM_RECOVERY_VERSION: 'packaging_jev_recovery'}

# B1 is stdlib-only, offline saved-public sampling; no execution route.
JM_SAMPLING_VERSION='jev_jm_sampling_public_v1'
JM_SAMPLING_PROTOCOLS={JM_SAMPLING_VERSION: 'packaging_jev_sampling'}

# B2 is a non-executable template and read-only saved-byte audit protocol.
JM_TRAINING_TEMPLATE_VERSION='jev_jm_training_template_v1'
JM_TRAINING_TEMPLATE_PROTOCOLS={JM_TRAINING_TEMPLATE_VERSION: 'packaging_jev_training_template'}
JM_SAVED_BYTES_AUDIT_VERSION='jev_jm_saved_bytes_audit_v1'

# Independent JM exact-v3 no-memory execution (not a training matrix).
JM_V13='jev_packaging_jm_no_memory_v13'
JM_V13_EXECUTION='jev_jm_v13_execution_v1'
JM_V13_PROTOCOLS={JM_V13_EXECUTION:'packaging_jev_v13'}

# B2 actual saved-byte plan preparation; no dispatch or permit issuance.
JM_TRAINING_PLAN_VERSION='jev_jm_training_plan_v1'
JM_TRAINING_PLAN_PROTOCOLS={JM_TRAINING_PLAN_VERSION:'packaging_jev_training_plan'}

# B2 final offline freeze/admission receipt, separate from the v1 preparation.
JM_TRAINING_FREEZE_VERSION='jev_jm_training_freeze_v1'
JM_TRAINING_FREEZE_PROTOCOLS={JM_TRAINING_FREEZE_VERSION:'packaging_jev_training_freeze'}

# JM2-A1 is offline public feature/role engineering, never an execution route.
JM_SCENARIO_INPUT='jev_jm_scenario_input_v1'
JM_SCENARIO_SIGNATURE='jev_jm_scenario_signature_v1'
JM_ACTION_CONTRAST='jev_jm_action_contrast_v1'
JM_SCENARIO_PROTOCOLS={v:'packaging_scenario_features' for v in
                       (JM_SCENARIO_INPUT,JM_SCENARIO_SIGNATURE,JM_ACTION_CONTRAST)}
JM_SCENARIO_SCHEMAS={JM_SCENARIO_INPUT:'jm_scenario_input_v1',
                     JM_SCENARIO_SIGNATURE:'jm_scenario_signature_v1',
                     JM_ACTION_CONTRAST:'jm_action_contrast_v1'}

# JM2-A2 archive-only nonempty projection; no retrieval/execution permit.
JM_T_PROJECTION='jev_jm_t_projection_v1'
JM_T_QUERY='jev_jm_t_query_v1'
JM_T_PROTOCOLS={v:'packaging_t_projection' for v in (JM_T_PROJECTION,JM_T_QUERY)}
JM_T_SCHEMAS={JM_T_PROJECTION:'jm_t_projection_v1',JM_T_QUERY:'jm_t_query_v1'}

# JM2-B1 limited offline contracts; deliberately no real admission or IO route.
JM_E_FACT_PACK='jev_jm_e_fact_pack_v1'
JM_E_GENERATION='jev_jm_e_generation_v1'
JM_E_GATE='jev_jm_e_gate_v1'
JM_E_PROMPT='jev_jm_e_prompt_contract_v1'
JM_E_RULES='jev_jm_e_prerequisite_rules_v1'
JM_E_PROTOCOLS={v:'packaging_experience_contract' for v in (JM_E_FACT_PACK,JM_E_GENERATION,JM_E_GATE,JM_E_PROMPT,JM_E_RULES)}
JM_E_SCHEMAS={JM_E_FACT_PACK:'jm_e_fact_pack_v1',JM_E_GENERATION:'jm_e_generation_v1',JM_E_GATE:'jm_e_gate_v1'}

# Bug-fix validation revision; existing v1 wire schemas remain unchanged.
JM_E_VALIDATION_REVISION='jev_jm_e_validation_v2'
JM_E_PROTOCOLS[JM_E_VALIDATION_REVISION]='packaging_experience_contract'
