"""Command-line interface for running the Ponder Coding Agent."""

import argparse
import os
import sys
from ponder.client import NebiusClient
from ponder.orchestrator import Orchestrator


def cli_event_logger(event_name: str, payload: dict):
    if event_name == "planning_start":
        print(f"\n[Ponder] Pipeline initiated...")
        print(f"         Requirement: {payload['requirement']}")
    elif event_name == "givens_complete":
        print(f"\n[Level 3] Hard Givens frozen:")
        print(f"          Target Language: {payload['target_language']}")
        print(f"          Protocols/Specs: {', '.join(payload['protocols']) or 'Standard'}")
        print(f"          Toolchain: compile='{payload['compile_cmd'] or 'none'}', test='{payload['test_cmd'] or 'none'}'")
    elif event_name == "planning_complete":

        print(f"[Level 2] Plan generated successfully:")
        print(f"          Summary: {payload['summary']}")
        print(f"          Topological Nodes ({payload['node_count']}): {' -> '.join(payload['execution_order'])}")
    elif event_name == "subgoal_start":
        print(f"\n  [Queue] Processing SubGoal: {payload['subgoal_id']}")
        print(f"          Target: {payload['module_path']}")
        print(f"          Prerequisites: {payload['dependencies'] or 'None (Root Node)'}")
    elif event_name == "chunk_attempt":
        print(f"  [Level 1] Actuator synthesizing chunk (Attempt {payload['attempt']})...")
    elif event_name == "verification_pass":
        print(f"  [Gate] PASS: SubGoal '{payload['subgoal_id']}' verified deterministically.")
    elif event_name == "verification_fail":
        print(f"  [Gate] FAIL: Stage: {payload['stage']}")
        print(f"         Error: {payload['error']}")
    elif event_name == "bottleneck_detected":
        print(f"  [Alert] Invariant bottleneck detected on '{payload['subgoal_id']}'! Triggering Level 2 replan...")
    elif event_name == "surgical_mutation":
        print(f"  [Level 2] Graph mutated surgically. Updated topological order: {' -> '.join(payload['new_order'])}")
    elif event_name == "assembly_complete":
        print(f"\n[Workspace] Assembly complete. Verified files written to disk:")
        for f in payload["files"]:
            print(f"  - {f}")


def main():
    parser = argparse.ArgumentParser(description="Ponder: Contract-Gated Topological Coding Agent Runner")
    parser.add_argument("requirement", help="User requirement or task specification")
    parser.add_argument(
        "--workspace",
        default="./output_workspace",
        help="Target directory for synthesized workspace",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in deterministic mock mode (offline/testing)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("NEBIUS_API_KEY")
    mock_mode = args.mock or (not api_key)

    client = NebiusClient(mock_mode=mock_mode)

    print("==================================================")
    print(" Ponder: Contract-Gated Topological Agent         ")
    print("==================================================")
    print(f"Provider: Nebius Token Factory (Mock Mode: {mock_mode})")
    print(f"Target Workspace: {args.workspace}")

    orchestrator = Orchestrator(
        workspace_dir=args.workspace,
        client=client,
        on_event=cli_event_logger,
    )

    result = orchestrator.run(args.requirement)
    print("\n[Complete] Agent execution finished successfully.")
    print(f"Verified sub-goals: {result['verified_subgoals']}")


if __name__ == "__main__":
    main()
