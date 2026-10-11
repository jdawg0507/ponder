"""Integration test for full end-to-end H-JEPA pipeline."""

from pathlib import Path
from ponder.client import NebiusClient
from ponder.orchestrator import Orchestrator


def test_orchestrator_end_to_end(tmp_path):
    events = []

    def capture_event(name, data):
        events.append((name, data))

    client = NebiusClient(mock_mode=True)
    orchestrator = Orchestrator(
        workspace_dir=str(tmp_path),
        client=client,
        on_event=capture_event,
    )

    result = orchestrator.run("Implement an LRU Cache backed by in-memory storage")

    assert result["status"] == "success"
    assert len(result["files"]) == 2
    assert "node_store" in result["verified_subgoals"]
    assert "node_cache" in result["verified_subgoals"]

    # Verify written files exist and have non-empty valid content
    store_file = tmp_path / "cache/store.py"
    cache_file = tmp_path / "cache/lru.py"

    assert store_file.exists()
    assert cache_file.exists()

    assert "MemoryStore" in store_file.read_text()
    assert "LRUCache" in cache_file.read_text()

    # Check key lifecycle events occurred in order
    event_names = [e[0] for e in events]
    assert "planning_start" in event_names
    assert "planning_complete" in event_names
    assert "subgoal_start" in event_names
    assert "verification_pass" in event_names
    assert "assembly_complete" in event_names


def test_orchestrator_fail_fast_aborts_downstream(tmp_path):
    events = []
    client = NebiusClient(mock_mode=True)
    orchestrator = Orchestrator(
        workspace_dir=str(tmp_path),
        client=client,
        on_event=lambda name, data: events.append((name, data)),
    )

    # Force the verifier to fail
    from ponder.models import VerificationResult
    orchestrator.verifier.verify = lambda *args, **kwargs: VerificationResult(
        passed=False, stage="test_harness", error_message="Injected verification failure"
    )

    result = orchestrator.run("Implement an LRU Cache backed by in-memory storage")

    assert result["status"] == "failed"
    assert "failed verification" in result["error"]

    event_names = [e[0] for e in events]
    assert "bottleneck_detected" in event_names
    assert "subgoal_aborted" in event_names  # Downstream node was aborted to save tokens
    # Assembly should never have been run
    assert "assembly_complete" not in event_names


def test_orchestrator_parallel_generation(tmp_path):
    events = []
    client = NebiusClient(mock_mode=True)
    orchestrator = Orchestrator(
        workspace_dir=str(tmp_path),
        client=client,
        on_event=lambda name, data: events.append((name, data)),
    )

    from ponder.models import SubGoal, SymbolContract, TopologyGraph, VerificationSpec

    # Create a plan where node_a and node_b have NO dependencies (generation 0 has 2 parallel nodes)
    node_a = SubGoal(
        id="node_a",
        module_path="mod_a.py",
        dependencies=[],
        public_contracts=[
            SymbolContract(
                symbol_name="func_a",
                symbol_type="function",
                signature="def func_a() -> str:",
                docstring="Doc A",
            )
        ],
        behavioral_invariants=["Invar A"],
        verification_spec=VerificationSpec(test_harness_code=""),
    )
    node_b = SubGoal(
        id="node_b",
        module_path="mod_b.py",
        dependencies=[],
        public_contracts=[
            SymbolContract(
                symbol_name="func_b",
                symbol_type="function",
                signature="def func_b() -> str:",
                docstring="Doc B",
            )
        ],
        behavioral_invariants=["Invar B"],
        verification_spec=VerificationSpec(test_harness_code=""),
    )

    parallel_graph = TopologyGraph(
        project_summary="Parallel independent modules",
        target_files=["mod_a.py", "mod_b.py"],
        nodes={"node_a": node_a, "node_b": node_b},
        execution_order=["node_a", "node_b"],
    )

    orchestrator.planner.plan = lambda *args, **kwargs: parallel_graph

    result = orchestrator.run("Generate two independent modules")
    assert result["status"] == "success"
    assert "node_a" in result["verified_subgoals"]
    assert "node_b" in result["verified_subgoals"]
    assert (tmp_path / "mod_a.py").exists()
    assert (tmp_path / "mod_b.py").exists()
