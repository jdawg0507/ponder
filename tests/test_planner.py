"""Unit tests for the Level 2 Topological Planner."""

import pytest
from ponder.client import NebiusClient
from ponder.models import SubGoal, SymbolContract, VerificationSpec
from ponder.planner import TopologicalPlanner


def test_planner_acyclic_dag_ordering():
    client = NebiusClient(mock_mode=True)
    planner = TopologicalPlanner(client)
    graph = planner.plan("Build a cache")

    assert len(graph.execution_order) == 2
    assert graph.execution_order == ["node_store", "node_cache"]
    assert "node_store" in graph.nodes
    assert "node_cache" in graph.nodes


def test_planner_cycle_rejection():
    client = NebiusClient(mock_mode=True)
    planner = TopologicalPlanner(client)

    raw_json_cyclic = """
    {
        "project_summary": "Cyclic test",
        "target_files": ["a.py", "b.py"],
        "nodes": {
            "node_a": {
                "id": "node_a",
                "module_path": "a.py",
                "dependencies": ["node_b"],
                "public_contracts": [],
                "behavioral_invariants": [],
                "verification_spec": {"test_harness_code": ""}
            },
            "node_b": {
                "id": "node_b",
                "module_path": "b.py",
                "dependencies": ["node_a"],
                "public_contracts": [],
                "behavioral_invariants": [],
                "verification_spec": {"test_harness_code": ""}
            }
        }
    }
    """

    with pytest.raises(ValueError, match="circular dependencies"):
        planner.parse_and_validate(raw_json_cyclic)


def test_planner_surgical_mutation():
    client = NebiusClient(mock_mode=True)
    planner = TopologicalPlanner(client)
    graph = planner.plan("Build a cache")

    mutated = planner.mutate_subgoal(graph, "node_cache", "Test harness assertion failed")
    assert "node_cache" not in mutated.nodes
    assert "node_cache_core" in mutated.nodes
    assert "node_cache_api" in mutated.nodes
    assert "node_cache_api" in mutated.execution_order
