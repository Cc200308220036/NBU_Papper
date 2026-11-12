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
