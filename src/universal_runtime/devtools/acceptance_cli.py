from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m universal_runtime.devtools.acceptance_cli")
    sub = parser.add_subparsers(dest="command", required=True)

    acc = sub.add_parser("acceptance")
    accsub = acc.add_subparsers(dest="action", required=True)
    run = accsub.add_parser("run")
    run.add_argument("spec")
    bootstrap = accsub.add_parser("bootstrap")
    bootstrap.add_argument("spec")

    action = sub.add_parser("action")
    actionsub = action.add_subparsers(dest="action", required=True)
    action_run = actionsub.add_parser("run")
    action_run.add_argument("spec")
    action_run.add_argument("--expected-sha256", required=True)
    action_gate = actionsub.add_parser("gate")
    action_gate.add_argument("spec")
    action_gate.add_argument("--expected-sha256", required=True)

    ns = parser.parse_args(argv)
    if ns.command == "acceptance" and ns.action == "run":
        from .acceptance_runner import run_acceptance

        report = run_acceptance(Path(ns.spec))
        print(json.dumps(report.to_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.data["result"] == "PASS" else 1
    if ns.command == "acceptance" and ns.action == "bootstrap":
        from .bootstrap_acceptance import run_bootstrap

        report = run_bootstrap(Path(ns.spec))
        print(json.dumps(report.to_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.data["result"] == "PASS" else 1
    if ns.command == "action" and ns.action == "run":
        from .action_acceptance import run_action_acceptance

        report = run_action_acceptance(Path(ns.spec), expected_spec_sha256=ns.expected_sha256)
        print(json.dumps(report.to_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.data["result"] == "PASS" else 1
    if ns.command == "action" and ns.action == "gate":
        from .action_delivery_gate import run_action_delivery_gate

        report = run_action_delivery_gate(Path(ns.spec), expected_spec_sha256=ns.expected_sha256)
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report["gate_result"] in {"PASS", "NO_OP"} else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
