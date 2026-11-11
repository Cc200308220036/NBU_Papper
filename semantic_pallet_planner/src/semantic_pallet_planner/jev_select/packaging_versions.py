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
