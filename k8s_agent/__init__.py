"""The Kubernetes-specific domain layer: LLM client, live-state queries,
execution, and security scanning. Supplies safety_core/'s interfaces
(RollbackPlanner, SuccessDefiner, AuditSink, Policy rules) with Kubernetes
domain details.
"""
