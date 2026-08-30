"""Thin I/O layer over a real Kubernetes cluster, via the kubernetes Python
client (never subprocess/shell strings — see OWASP: no OS commands built
from data). Does I/O and populates DeploymentState/ExecutionResult/
DryRunDiff objects only. No classification logic (that's the Gate,
safety_core/) and no translation logic beyond populating DeploymentState
(that's k8s_agent/state_builder.py's job) — this module still never
imports Gate, Policy, Decision, or State; the one exception is Action
(dry_run_diff's parameter), safety_core's own designated domain-agnostic
value type ("Domain layers populate them" — safety_core/types.py), no
different in kind from k8s_agent/agent.py already importing it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from k8s_agent.cluster_types import DeploymentState, DryRunDiff
from safety_core.types import Action

_REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
_OBSERVE_POLL_INTERVAL_SECONDS = 2
_OBSERVE_DEFAULT_TIMEOUT_SECONDS = 45


class DeploymentNotFoundError(Exception):
    """Raised by get_deployment_state when the named Deployment doesn't
    exist. A read-time "not found" is a meaningful fork the caller must
    handle explicitly, so this raises rather than returning None or a
    sentinel DeploymentState (which has no field to represent "missing").
    """


@dataclass(frozen=True)
class ExecutionResult:
    """The outcome of an execute method: whether it succeeded, plus
    whatever detail is useful for the caller/audit trail.
    """

    success: bool
    detail: dict[str, Any]


class ClusterClient:
    """Read/execute access to one Kubernetes cluster.

    Execute methods (scale/restart/update-limits/delete-pod) catch API
    failures and report them via ExecutionResult(success=False, ...) —
    per the read/write split, a write's success is already part of its
    contract. delete_persistent_volume_claim is simulated: it never calls
    the real delete API, since PVC deletion is the one irreversible action
    this demo must not actually perform.
    """

    def __init__(self, api_client: client.ApiClient | None = None) -> None:
        if api_client is None:
            config.load_kube_config()
            api_client = client.ApiClient()
        self._apps = client.AppsV1Api(api_client)
        self._core = client.CoreV1Api(api_client)
        self._policy = client.PolicyV1Api(api_client)

    def get_deployment_state(self, name: str, namespace: str) -> DeploymentState:
        """Fetch and translate one Deployment's live state.

        Raises DeploymentNotFoundError if `name` doesn't exist in
        `namespace`. mid_batch is a proxy for "a rollout is actively in
        progress": status.updated_replicas hasn't yet caught up to
        spec.replicas.
        """
        deployment = self._read_deployment(name, namespace)

        app_label = deployment.spec.selector.match_labels.get("app", name)
        label_selector = f"app={app_label}"

        healthy_replicas = deployment.status.ready_replicas or 0
        desired_replicas = deployment.spec.replicas or 0
        updated_replicas = deployment.status.updated_replicas or 0
        mid_batch = updated_replicas < desired_replicas

        pdb_min_available = self._pdb_min_available(namespace, app_label)
        revisions = self._revision_history(namespace, label_selector)

        return DeploymentState(
            namespace=namespace,
            healthy_replicas=healthy_replicas,
            desired_replicas=desired_replicas,
            pdb_min_available=pdb_min_available,
            revisions=revisions,
            mid_batch=mid_batch,
        )

    def _pdb_min_available(self, namespace: str, app_label: str) -> int | None:
        """The matching PodDisruptionBudget's minAvailable, or None if no
        PDB selects these pods (or its minAvailable isn't a plain int —
        percentage-based budgets aren't handled by this demo).

        Lists every PDB in the namespace rather than filtering server-side
        by label_selector: that query param matches a PDB's own metadata
        labels, not the pods its spec.selector targets — PDBs are usually
        authored with no labels of their own, so a label_selector filter
        here would silently match nothing. Matching spec.selector.match_labels
        client-side is the correct way to find the PDB governing this
        deployment's pods.
        """
        budgets = self._policy.list_namespaced_pod_disruption_budget(namespace)
        for budget in budgets.items:
            selector = budget.spec.selector
            selector_labels = selector.match_labels if selector and selector.match_labels else {}
            if selector_labels.get("app") != app_label:
                continue
            min_available = budget.spec.min_available
            if isinstance(min_available, int):
                return min_available
        return None

    def _read_deployment(self, name: str, namespace: str) -> Any:
        try:
            return self._apps.read_namespaced_deployment(name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                raise DeploymentNotFoundError(f"Deployment '{name}' not found in namespace '{namespace}'") from exc
            raise

    def observe_outcome(
        self, deployment: str, namespace: str, metric: str, timeout_seconds: int = _OBSERVE_DEFAULT_TIMEOUT_SECONDS
    ) -> dict[str, int]:
        """Wait for `deployment`'s rollout to reach a terminal state
        (settled — native Kubernetes readiness reached — or timeout),
        then read `metric` off its status and return {metric: value}:
        exactly the `observed` shape safety_core.success.check_regression
        expects, so a caller can pass this straight through.

        "Settled" is Kubernetes' own rollout-completion signal — the same
        computation `kubectl rollout status` uses (observedGeneration
        caught up, updatedReplicas/availableReplicas/replicas all equal
        to spec.replicas) — not a heuristic this method invents.
        Not-ready-by-timeout is not an error: the observed (likely
        below-target) value is returned as-is, since that value IS the
        regression signal check_regression exists to catch.
        """
        deadline = time.monotonic() + timeout_seconds
        current = self._read_deployment(deployment, namespace)
        while not self._rollout_settled(current) and time.monotonic() < deadline:
            time.sleep(_OBSERVE_POLL_INTERVAL_SECONDS)
            current = self._read_deployment(deployment, namespace)
        return {metric: self._read_metric(current, metric)}

    @staticmethod
    def _rollout_settled(deployment: Any) -> bool:
        spec_replicas = deployment.spec.replicas or 0
        status = deployment.status
        generation = deployment.metadata.generation or 0
        if (status.observed_generation or 0) < generation:
            return False
        if (status.updated_replicas or 0) < spec_replicas:
            return False
        if (status.replicas or 0) > (status.updated_replicas or 0):
            return False
        if (status.available_replicas or 0) < (status.updated_replicas or 0):
            return False
        return True

    @staticmethod
    def _read_metric(deployment: Any, metric: str) -> int:
        if metric == "healthy_replicas":
            return deployment.status.ready_replicas or 0
        raise ValueError(f"observe_outcome: unsupported metric {metric!r}")

    def _revision_history(self, namespace: str, label_selector: str) -> list[int]:
        """Every revision number recorded on this Deployment's ReplicaSets,
        oldest first — including scaled-to-zero ones, which are still valid
        rollback targets.
        """
        replica_sets = self._apps.list_namespaced_replica_set(namespace, label_selector=label_selector)
        revisions = []
        for rs in replica_sets.items:
            raw = (rs.metadata.annotations or {}).get(_REVISION_ANNOTATION)
            if raw is not None:
                revisions.append(int(raw))
        return sorted(revisions)

    def scale_deployment(self, name: str, namespace: str, replicas: int) -> ExecutionResult:
        try:
            self._apps.patch_namespaced_deployment_scale(name, namespace, {"spec": {"replicas": replicas}})
            return ExecutionResult(success=True, detail={"replicas": replicas})
        except ApiException as exc:
            return ExecutionResult(success=False, detail={"error": str(exc), "status": exc.status})

    def restart_deployment(self, name: str, namespace: str) -> ExecutionResult:
        """Patch the pod template's restart annotation — the same
        mechanism `kubectl rollout restart` uses; always creates a new
        revision.
        """
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()}
                    }
                }
            }
        }
        try:
            self._apps.patch_namespaced_deployment(name, namespace, patch)
            return ExecutionResult(success=True, detail={})
        except ApiException as exc:
            return ExecutionResult(success=False, detail={"error": str(exc), "status": exc.status})

    def update_resource_limits(
        self,
        name: str,
        namespace: str,
        container: str,
        *,
        cpu: str | None = None,
        memory: str | None = None,
    ) -> ExecutionResult:
        limits: dict[str, str] = {}
        if cpu is not None:
            limits["cpu"] = cpu
        if memory is not None:
            limits["memory"] = memory
        patch = {
            "spec": {
                "template": {
                    "spec": {"containers": [{"name": container, "resources": {"limits": limits}}]}
                }
            }
        }
        try:
            self._apps.patch_namespaced_deployment(name, namespace, patch)
            return ExecutionResult(success=True, detail={"container": container, "limits": limits})
        except ApiException as exc:
            return ExecutionResult(success=False, detail={"error": str(exc), "status": exc.status})

    def delete_pod(self, name: str, namespace: str) -> ExecutionResult:
        try:
            self._core.delete_namespaced_pod(name, namespace)
            return ExecutionResult(success=True, detail={"pod": name})
        except ApiException as exc:
            return ExecutionResult(success=False, detail={"error": str(exc), "status": exc.status})

    def delete_persistent_volume_claim(self, name: str, namespace: str) -> ExecutionResult:
        """SIMULATED — this is the one irreversible action in the demo.
        Never calls the real delete API, regardless of arguments.
        """
        return ExecutionResult(
            success=True,
            detail={"simulated": True, "pvc": name, "note": "PVC deletion is simulated — no real delete was performed."},
        )

    def dry_run_diff(self, action: Action) -> DryRunDiff | None:
        """A read-only preview of what `action` would change, via a real
        server-side dry run (dry_run="All") — runs the change through the
        full admission pipeline and returns the resulting object without
        persisting anything. Operator-preview only: never wired into
        classification, the Gate already made the safety decision before
        this is ever called. Fails soft on purpose (any exception, not
        just ApiException) — a broken preview must never crash the CLI or
        block a decision; it's informational, not a safety gate.
        """
        try:
            if action.tool == "scale_deployment":
                return self._dry_run_scale(
                    action.args["deployment"], action.args["namespace"], action.args["target_replicas"]
                )
            if action.tool == "restart_deployment":
                return self._dry_run_restart(action.args["deployment"], action.args["namespace"])
            if action.tool == "update_resource_limits":
                return self._dry_run_update_resource_limits(
                    action.args["deployment"],
                    action.args["namespace"],
                    action.args["container"],
                    memory=action.args.get("memory_limit"),
                )
            if action.tool == "delete_pod":
                return self._dry_run_delete_pod(action.args["pod"], action.args["namespace"])
            if action.tool == "delete_persistent_volume_claim":
                return DryRunDiff(
                    kind="simulated_removal",
                    changes={},
                    description=(
                        f"PVC '{action.args['pvc']}' deletion is simulated in this demo — "
                        "no real dry run is performed."
                    ),
                )
            return None  # get_pod_logs (read-only) and anything unrecognized
        except Exception:
            return None

    def _dry_run_scale(self, name: str, namespace: str, target_replicas: int) -> DryRunDiff:
        current = self._apps.read_namespaced_deployment(name, namespace)
        result = self._apps.patch_namespaced_deployment_scale(
            name, namespace, {"spec": {"replicas": target_replicas}}, dry_run="All"
        )
        return DryRunDiff(
            kind="field_delta", changes={"replicas": (current.spec.replicas, result.spec.replicas)}, description=None
        )

    def _dry_run_restart(self, name: str, namespace: str) -> DryRunDiff:
        current = self._apps.read_namespaced_deployment(name, namespace)
        old_annotation = self._restarted_at(current)
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()}
                    }
                }
            }
        }
        result = self._apps.patch_namespaced_deployment(name, namespace, patch, dry_run="All")
        new_annotation = self._restarted_at(result)
        return DryRunDiff(kind="field_delta", changes={"restartedAt": (old_annotation, new_annotation)}, description=None)

    def _dry_run_update_resource_limits(
        self, name: str, namespace: str, container: str, *, cpu: str | None = None, memory: str | None = None
    ) -> DryRunDiff:
        current = self._apps.read_namespaced_deployment(name, namespace)
        old_limits = self._container_limits(current, container)
        limits: dict[str, str] = {}
        if cpu is not None:
            limits["cpu"] = cpu
        if memory is not None:
            limits["memory"] = memory
        patch = {
            "spec": {"template": {"spec": {"containers": [{"name": container, "resources": {"limits": limits}}]}}}
        }
        result = self._apps.patch_namespaced_deployment(name, namespace, patch, dry_run="All")
        new_limits = self._container_limits(result, container)
        return DryRunDiff(kind="field_delta", changes={"limits": (old_limits, new_limits)}, description=None)

    def _dry_run_delete_pod(self, name: str, namespace: str) -> DryRunDiff:
        self._core.delete_namespaced_pod(name, namespace, dry_run="All")
        return DryRunDiff(kind="removal", changes={}, description=f"Pod '{name}' would be removed.")

    @staticmethod
    def _restarted_at(deployment: Any) -> str | None:
        return (deployment.spec.template.metadata.annotations or {}).get("kubectl.kubernetes.io/restartedAt")

    @staticmethod
    def _container_limits(deployment: Any, container_name: str) -> dict[str, str]:
        for container in deployment.spec.template.spec.containers:
            if container.name == container_name:
                return dict(container.resources.limits or {}) if container.resources else {}
        return {}

    def resolve_pod_owner(self, pod_name: str, namespace: str) -> str:
        """Walk ownerReferences: pod -> ReplicaSet -> Deployment, returning
        the Deployment's name.

        Raises DeploymentNotFoundError for every genuine not-found case —
        the pod itself is gone, it has no owning ReplicaSet (e.g. a bare
        pod), the ReplicaSet is gone, or the ReplicaSet has no owning
        Deployment. Never a catch-all: each of these is a real absence, not
        a guess (a pod name is not "deployment-name + hash" reliably, so
        this walks the actual ownerReferences chain rather than string
        -matching the name).
        """
        try:
            pod = self._core.read_namespaced_pod(pod_name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                raise DeploymentNotFoundError(f"Pod '{pod_name}' not found in namespace '{namespace}'") from exc
            raise

        rs_name = self._controller_owner_name(pod.metadata.owner_references, "ReplicaSet")
        if rs_name is None:
            raise DeploymentNotFoundError(f"Pod '{pod_name}' has no owning ReplicaSet in namespace '{namespace}'")

        try:
            replica_set = self._apps.read_namespaced_replica_set(rs_name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                raise DeploymentNotFoundError(f"ReplicaSet '{rs_name}' not found in namespace '{namespace}'") from exc
            raise

        deployment_name = self._controller_owner_name(replica_set.metadata.owner_references, "Deployment")
        if deployment_name is None:
            raise DeploymentNotFoundError(f"ReplicaSet '{rs_name}' has no owning Deployment in namespace '{namespace}'")
        return deployment_name

    @staticmethod
    def _controller_owner_name(owner_references: list[Any] | None, kind: str) -> str | None:
        for owner in owner_references or []:
            if owner.kind == kind and owner.controller:
                return owner.name
        return None
