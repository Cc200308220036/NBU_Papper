"""Explicit registration for the independently versioned exact-pose protocol."""
EXACT_VERSION='jev_packaging_synthetic_v12'
EXACT_CONTEXT='jev_decision_context_v12'
EXACT_BUNDLE='jev_candidate_bundle_v12'
EXACT_PLAN='jev_synthetic_supplement_plan_v2'
EXACT_RUN='jev_synthetic_supplement_run_v2'
REMAINDER_PLAN='jev_synthetic_remainder_plan_v3'

# GP3-N2 permits candidate/F0 construction only. No execution or checkpoint route.
GEOMETRY_VERSION='jev_packaging_geometry_compare_v14'
GEOMETRY_BUNDLE='jev_candidate_bundle_v14'
GEOMETRY_CONTEXT='jev_decision_context_v14'
GEOMETRY_SCHEMAS={'config': 'config_v14', 'candidate_bundle':'candidate_bundle_v14',
                  'decision_context':'decision_context_v14'}
GEOMETRY_COMMON_BINDING='geometry_common_input_binding_v1'
GEOMETRY_BACKEND_BINDING='geometry_backend_binding_v1'
GEOMETRY_ADMISSION='geometry_common_admission_v1'
GEOMETRY_AUDIT='geometry_provider_audit_v1'
GEOMETRY_BACKENDS=('e2_original_v1','ems_surface_hybrid_v1')
DEFAULT_GEOMETRY_BACKEND='ems_surface_hybrid_v1'


def reject_geometry_execution(config_or_context, operation):
    if config_or_context.get('version') in (GEOMETRY_VERSION, GEOMETRY_CONTEXT):
        from .contracts import JevSelectError
        raise JevSelectError('geometry_construction_only', operation)

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

# REV1 pure F-S geometry; no transport, memory or execution registration.
JM_FS_INPUT='jev_jm_fs_input_v1'
JM_FS_RESULT='jev_jm_fs_result_v1'
JM_FS_ALGORITHM='jm_fs_floor_grid_neighbor_v1'
JM_FS_PROTOCOLS={v:'packaging_fs_geometry' for v in (JM_FS_INPUT,JM_FS_RESULT)}
JM_FS_SCHEMAS={JM_FS_INPUT:'jm_fs_input_v1',JM_FS_RESULT:'jm_fs_result_v1'}

# GP3-N3 hand-fixture execution, independent of construction-only v14.
GEOMETRY_RUN_VERSION='jev_packaging_geometry_run_v15'
GEOMETRY_RUN_CONTEXT='jev_decision_context_v15'
GEOMETRY_RUN_BUNDLE='jev_candidate_bundle_v15'
GEOMETRY_EXECUTION='geometry_fixture_execution_v1'
GEOMETRY_RUN_SCHEMAS={k:k+'_v15' for k in
    ('config','candidate_bundle','decision_context','selection_result','checkpoint')}
GEOMETRY_RUN_SCHEMAS['geometry_execution']='geometry_execution_v1'
GEOMETRY_CONFIGS=(GEOMETRY_VERSION,GEOMETRY_RUN_VERSION)
GEOMETRY_BUNDLES=(GEOMETRY_BUNDLE,GEOMETRY_RUN_BUNDLE)
GEOMETRY_CONTEXTS=(GEOMETRY_CONTEXT,GEOMETRY_RUN_CONTEXT)

GEOMETRY_RUN_SCHEMAS['geometry_metrics']='geometry_metrics_v1'

# GP5: independent real-order plumbing; development, acceptance and order gates.
GEOMETRY_ORDER_VERSION='jev_packaging_geometry_order_v16'
GEOMETRY_ORDER_CONTEXT='jev_decision_context_v16'
GEOMETRY_ORDER_BUNDLE='jev_candidate_bundle_v16'
GEOMETRY_ORDER_SCHEMAS={k:k+'_v16' for k in
    ('config','candidate_bundle','decision_context','selection_result','checkpoint')}
GEOMETRY_ORDER_SCHEMAS.update({k:k for k in ('geometry_order_plan_v1','geometry_order_execution_v1',
    'geometry_order_metrics_v1','geometry_order_run_v1','geometry_development_binding_v1',
    'geometry_kernel_launch_v1','geometry_order_admission_v1','geometry_real_kernel_receipt_v1',
    'geometry_scope_authorization_v1','geometry_scope_review_v1')})
GEOMETRY_EXECUTABLE_CONFIGS=(GEOMETRY_RUN_VERSION,GEOMETRY_ORDER_VERSION)
GEOMETRY_CONFIGS=(*GEOMETRY_CONFIGS,GEOMETRY_ORDER_VERSION)
GEOMETRY_BUNDLES=(*GEOMETRY_BUNDLES,GEOMETRY_ORDER_BUNDLE)
GEOMETRY_CONTEXTS=(*GEOMETRY_CONTEXTS,GEOMETRY_ORDER_CONTEXT)

# GP5 P1-R1 closed completion and independent invocation accounting.
GEOMETRY_ORDER_SCHEMAS.update({k:k for k in (
    "geometry_real_kernel_receipt_v2", "geometry_kernel_completion_review_v1",
    "geometry_order_accounting_v1", "geometry_phase_snapshot_credential_v1")})

# NUM-N1: explicit opt-in publication contract; no fallback or suffix guessing.
GEOMETRY_NATIVE_VERSION='jev_packaging_geometry_order_v17'
GEOMETRY_NATIVE_CONTEXT='jev_decision_context_v17'
GEOMETRY_NATIVE_BUNDLE='jev_candidate_bundle_v17'
GEOMETRY_NATIVE_POLICY='geometry_native_shape_publication_policy_v3'
GEOMETRY_NATIVE_BRIDGE='geometry_runtime_native_shape_bridge_v3'
GEOMETRY_NATIVE_SCHEMAS={k:k+'_v17' for k in ('config','candidate_bundle','decision_context','selection_result','checkpoint')}
GEOMETRY_NATIVE_SCHEMAS.update({k:k for k in ('native_shape_shadow_core','native_shape_derived_core','native_shape_equivalence','native_shape_proof_core','native_shape_shadow_binding','native_shape_final_binding','native_shape_publication')})
GEOMETRY_NATIVE_CAPABILITIES={GEOMETRY_NATIVE_VERSION:{'policy':GEOMETRY_NATIVE_POLICY,'bridge':GEOMETRY_NATIVE_BRIDGE,'id_pattern':r'^GP5N3_[0-9a-f]{64}$','schemas':GEOMETRY_NATIVE_SCHEMAS}}

GEOMETRY_EXECUTABLE_CONFIGS=(*GEOMETRY_EXECUTABLE_CONFIGS,GEOMETRY_NATIVE_VERSION)
GEOMETRY_CONFIGS=(*GEOMETRY_CONFIGS,GEOMETRY_NATIVE_VERSION)
GEOMETRY_BUNDLES=(*GEOMETRY_BUNDLES,GEOMETRY_NATIVE_BUNDLE)
GEOMETRY_CONTEXTS=(*GEOMETRY_CONTEXTS,GEOMETRY_NATIVE_CONTEXT)
GEOMETRY_ORDER_CONFIGS=(GEOMETRY_ORDER_VERSION,GEOMETRY_NATIVE_VERSION)

GEOMETRY_NATIVE_SCHEMAS.update({k:k for k in ('geometry_order_plan_v2', 'geometry_order_execution_v2', 'geometry_order_metrics_v2', 'geometry_order_run_v2', 'geometry_order_accounting_v2', 'geometry_development_binding_v2', 'geometry_kernel_launch_v2', 'geometry_order_admission_v2', 'geometry_scope_authorization_v2', 'geometry_scope_review_v2', 'geometry_real_kernel_receipt_v3', 'geometry_kernel_completion_review_v2', 'geometry_phase_snapshot_credential_v2', 'geometry_operational_order_plan_v1')})
GEOMETRY_OPERATIONAL_PLAN='geometry_operational_order_plan_v1'
