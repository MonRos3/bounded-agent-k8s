"""Thin I/O layer over a real Kubernetes cluster, via the kubernetes Python
client (never subprocess/shell strings — see OWASP: no OS commands built
from data). Does I/O and populates DeploymentState/ExecutionResult objects
only. No classification logic (that's the Gate, safety_core/) and no
translation logic beyond populating DeploymentState (that's
k8s_agent/state_builder.py's job) — this module never imports safety_core/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from k8s_agent.cluster_types import DeploymentState

_REVISION_ANNOTATION = "deployment.kubernetes.io/revision"


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
        try:
            deployment = self._apps.read_namespaced_deployment(name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                raise DeploymentNotFoundError(f"Deployment '{name}' not found in namespace '{namespace}'") from exc
            raise

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
