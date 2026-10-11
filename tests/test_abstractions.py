"""Unit tests for LanguageProfile, TopologyResolver, and DiagnosticAnalyzer abstractions."""

import pytest
from ponder.diagnostics import DiagnosticAnalyzer, DiagnosticCategory
from ponder.languages import GoProfile, LanguageRegistry, PythonProfile
from ponder.models import ChunkOutput, SubGoal, TopologyGraph, VerificationSpec
from ponder.planner import TopologyResolver


def test_topology_resolver_prunes_ghost_dependencies():
    """Ensures ghost references (like existing files or unmapped IDs) don't crash the DAG."""
    nodes = {
        "node_1": SubGoal(
            id="node_1",
            module_path="src/main.cpp",
            dependencies=["src/char.cpp", "phantom_ghost_id"],  # Ghost dependencies!
            verification_spec=VerificationSpec(test_harness_code=""),
        ),
        "node_2": SubGoal(
            id="node_2",
            module_path="src/utils.cpp",
            dependencies=["node_1", "src/helper.h"],
            verification_spec=VerificationSpec(test_harness_code=""),
        ),
    }

    graph = TopologyGraph(
        project_summary="Test",
        target_files=["src/main.cpp", "src/utils.cpp"],
        nodes=nodes,
    )

    resolved = TopologyResolver.resolve_and_order(graph)

    # Ghost dependencies were pruned; valid DAG edge node_1 -> node_2 was preserved
    assert resolved.nodes["node_1"].dependencies == []
    assert resolved.nodes["node_2"].dependencies == ["node_1"]
    assert resolved.execution_order == ["node_1", "node_2"]


def test_topology_resolver_detects_real_cycles():
    """Ensures real circular dependencies between nodes are still caught."""
    nodes = {
        "node_a": SubGoal(
            id="node_a",
            module_path="a.py",
            dependencies=["node_b"],
            verification_spec=VerificationSpec(test_harness_code=""),
        ),
        "node_b": SubGoal(
            id="node_b",
            module_path="b.py",
            dependencies=["node_a"],
            verification_spec=VerificationSpec(test_harness_code=""),
        ),
    }

    graph = TopologyGraph(project_summary="Cyclic", target_files=["a.py", "b.py"], nodes=nodes)
    with pytest.raises(ValueError, match="circular dependencies"):
        TopologyResolver.resolve_and_order(graph)


def test_go_language_profile_assembly():
    """Ensures GoProfile always places package main on line 1 followed by import block."""
    profile = LanguageRegistry.get("go")
    assert isinstance(profile, GoProfile)
    assert profile.shares_directory_scope is True

    chunks = [
        ChunkOutput(
            subgoal_id="n1",
            code='package main\n\nimport "fmt"\n\nfunc Hello() string { return "hi" }',
            imports=['"fmt"'],
        ),
        ChunkOutput(
            subgoal_id="n2",
            code='import "os"\nimport "fmt"\n\nfunc Main() { fmt.Println(Hello()) }',
            imports=['"os"', '"fmt"'],
        ),
    ]

    assembled = profile.assemble_source(chunks)
    lines = assembled.splitlines()

    # Package must be the first line
    assert lines[0] == "package main"
    # Imports must be formatted as import (...) block
    assert "import (" in assembled
    assert '"fmt"' in assembled
    assert '"os"' in assembled
    assert "func Hello" in assembled
    assert "func Main" in assembled


def test_diagnostic_analyzer():
    """Ensures DiagnosticAnalyzer categorizes compiler errors into structured directives."""
    redecl_diag = DiagnosticAnalyzer.analyze(
        "command_handler.go:23:6: other declaration of ParseRESPArray\nParseRESPArray redeclared in this block",
        language="go",
    )
    assert redecl_diag.category == DiagnosticCategory.REDECLARATION
    assert "redeclared" in redecl_diag.remediation_directive.lower()

    header_diag = DiagnosticAnalyzer.analyze(
        "app/main.go:1:1: expected 'package', found 'import'",
        language="go",
    )
    assert header_diag.category == DiagnosticCategory.HEADER_ORDERING
    assert "package" in header_diag.remediation_directive.lower()
