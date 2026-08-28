"""The domain-independent safety spine: policy, gate, rollback, success,
guardrails, and audit. Contains zero domain-specific (Kubernetes, Terraform,
cloud) code — domain behavior enters only through the interfaces defined in
this package (RollbackPlanner, SuccessDefiner, AuditSink, Policy, State).
"""
