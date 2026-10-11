"""H-JEPA Inspired Coding Agent Core Data Models."""

from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class SymbolContract(BaseModel):
    """Immutable public contract for a symbol (function, class, struct, type, method, or interface)."""
    symbol_name: str
    symbol_type: str = "function"  # e.g., "function", "method", "class", "struct", "type", "interface"
    signature: str
    docstring: str = ""
    raises: List[str] = Field(default_factory=list)


class ToolchainConfig(BaseModel):
    """Deterministic commands for checking syntax, types, and running tests."""
    compile_cmd: Optional[str] = None  # e.g., "cargo check", "go build -o /dev/null", "python -m py_compile"
    test_cmd: Optional[str] = None     # e.g., "cargo test", "go test ./...", "pytest"
    lint_cmd: Optional[str] = None     # e.g., "cargo clippy", "go vet", "ruff check"


class HardGivens(BaseModel):
    """Level 3 Invariant Anchor freezing problem non-negotiables."""
    target_language: Literal["python", "rust", "go", "typescript", "c", "cpp", "java", "generic"] = "python"
    toolchain: ToolchainConfig = Field(default_factory=ToolchainConfig)
    protocols_and_specs: List[str] = Field(default_factory=list)
    allowed_dependencies: List[str] = Field(default_factory=list)
    boundary_constraints: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    existing_files: List[str] = Field(default_factory=list)


class VerificationSpec(BaseModel):
    """Specification for deterministic verification of a sub-goal."""
    syntax_parser: str = "compiler"
    type_stubs_required: List[str] = Field(default_factory=list)
    test_harness_code: str = ""  # Standalone test snippet (for in-memory evaluation)
    custom_verify_cmd: Optional[str] = None  # Custom CLI command (e.g. "codecrafters test")



class SubGoal(BaseModel):
    """An atomic unit of planning and execution in the topological DAG."""
    id: str
    module_path: str  # Target file path (e.g. "cache/lru.py")
    dependencies: List[str] = Field(default_factory=list)  # Prerequisite SubGoal IDs
    public_contracts: List[SymbolContract] = Field(default_factory=list)
    private_scope_allowed: bool = True
    behavioral_invariants: List[str] = Field(default_factory=list)
    verification_spec: VerificationSpec
    status: Literal["pending", "verifying", "verified", "failed"] = "pending"
    attempts: int = 0

class TopologyGraph(BaseModel):
    """Level 2 structural specification containing invariant-governed DAG."""
    project_summary: str = "Synthesized Software Architecture"
    target_files: List[str] = Field(default_factory=list)
    nodes: Dict[str, SubGoal]
    execution_order: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_graph_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # Handle nodes passed as a list
        raw_nodes = data.get("nodes")
        if isinstance(raw_nodes, list):
            dict_nodes = {}
            for idx, item in enumerate(raw_nodes):
                if isinstance(item, dict):
                    node_id = item.get("id") or item.get("name") or f"node_{idx+1}"
                    item["id"] = node_id
                    if "module_path" not in item:
                        item["module_path"] = item.get("name") or "main.py"
                    if "public_contracts" not in item:
                        item["public_contracts"] = []
                    dict_nodes[node_id] = item
            data["nodes"] = dict_nodes

        # Handle target_files auto-population
        if not data.get("target_files") and isinstance(data.get("nodes"), dict):
            files = set()
            for n in data["nodes"].values():
                if isinstance(n, dict) and "module_path" in n:
                    files.add(n["module_path"])
                elif hasattr(n, "module_path"):
                    files.add(n.module_path)
            data["target_files"] = sorted(list(files))

        return data


class ChunkOutput(BaseModel):
    """Level 1 realized code chunk."""
    subgoal_id: str
    code: str
    imports: List[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Deterministic verification gate result."""
    passed: bool
    stage: Literal["syntax", "signature", "typing", "test_harness"] = "syntax"
    error_message: Optional[str] = None
    details: Optional[str] = None
