"""The operator's compliance entry point — separate from the agent's
REPL (k8s_agent/cli.py) on purpose: you don't scan compliance from
inside the agent's interactive loop, it's its own operator command. No
LLM, no gate, no agent involvement.
"""

from __future__ import annotations

import argparse

from rich.console import Console

from compliance.report import persist_evidence, render_report
from compliance.scan import scan_cluster


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan the cluster's Kubernetes-layer SOC 2 posture.")
    parser.add_argument("--namespace", default=None, help="Limit the scan to one namespace (default: whole cluster).")
    parser.add_argument("--framework", default="soc2")
    args = parser.parse_args()

    console = Console()
    result = scan_cluster(namespace=args.namespace, framework=args.framework)
    render_report(result, console)

    json_path, md_path = persist_evidence(result)
    console.print(f"\n[dim]evidence written: {json_path}[/dim]")
    console.print(f"[dim]evidence written: {md_path}[/dim]")


if __name__ == "__main__":
    main()
