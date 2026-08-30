"""The Kubernetes-specific domain layer: LLM client, live-state queries,
and execution. Supplies safety_core/'s interfaces (RollbackPlanner,
SuccessDefiner, AuditSink, Policy rules) with Kubernetes domain details.

Compliance/posture scanning (Kubescape) lives in compliance/, not here:
it's a human-operator capability with no LLM, gate, or agent involvement
— a deliberately separate sibling package, not a k8s_agent/ concern.
"""
