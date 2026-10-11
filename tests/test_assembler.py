"""Unit tests for the Workspace Assembler."""

from ponder.assembler import WorkspaceAssembler
from ponder.models import ChunkOutput, SubGoal, VerificationSpec


def test_workspace_assembler_merge(tmp_path):
    assembler = WorkspaceAssembler(str(tmp_path))

    subgoals = {
        "node_1": SubGoal(
            id="node_1",
            module_path="utils/math.py",
            dependencies=[],
            verification_spec=VerificationSpec(test_harness_code=""),
        ),
        "node_2": SubGoal(
            id="node_2",
            module_path="utils/math.py",
            dependencies=["node_1"],
            verification_spec=VerificationSpec(test_harness_code=""),
        ),
    }

    chunks = {
        "node_1": ChunkOutput(
            subgoal_id="node_1",
            code="import math\n\ndef square(x: float) -> float:\n    return x * x\n",
            imports=["import math"],
        ),
        "node_2": ChunkOutput(
            subgoal_id="node_2",
            code="import math\n\ndef cube(x: float) -> float:\n    return x * x * x\n",
            imports=["import math"],
        ),
    }

    written = assembler.assemble(subgoals, chunks)
    assert len(written) == 1

    content = (tmp_path / "utils/math.py").read_text()
    # Ensure import is not duplicated
    assert content.count("import math") == 1
    assert "def square" in content
    assert "def cube" in content
