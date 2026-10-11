"""Level 2 Macro-Topological Planner for Ponder Coding Agent."""

from __future__ import annotations
import json
from typing import Dict, List, Optional
import networkx as nx
from pydantic import ValidationError

from ponder.client import LEVEL_2_DEFAULT_MODEL, NebiusClient
from ponder.models import SubGoal, SymbolContract, TopologyGraph, VerificationSpec


LEVEL_2_SYSTEM_PROMPT = """You are the Level 2 Macro-Topological Planner in the Ponder Coding Agent architecture.
Your duty is to act as the strategic software architect: break down complex requirements and large codebase context into clear, atomic microsteps that an actuator LLM can implement with high precision.
The sum of the parts must equal the whole. Every microstep must keep the workspace in a compilable state.

CRITICAL INVARIANTS:
1. CODE GENERATION IS STRICTLY FORBIDDEN AT THIS LAYER. Do not write function bodies or implementation algorithms.
2. Emit ONLY a valid JSON object matching this structure:
{
  "project_summary": "High-level summary of the system architecture",
  "target_files": ["math_utils.py"],
  "nodes": {
    "node_id": {
      "id": "node_id",
      "module_path": "math_utils.py",
      "dependencies": [],
      "public_contracts": [
        {
          "symbol_name": "add",
          "symbol_type": "function",
          "signature": "def add(a: int, b: int) -> int:",
          "docstring": "Adds two integers.",
          "raises": []
        }
      ],
      "behavioral_invariants": ["Returns sum of a and b"],
      "verification_spec": {
        "syntax_parser": "python_ast",
        "type_stubs_required": [],
        "test_harness_code": "def test_add():\\n    assert add(1, 2) == 3\\n"
      }
    }
  }
}
3. Dependencies must form a strictly acyclic graph (DAG). Foundational contracts must come first.
4. For structs, classes, or types (e.g. in Go, Rust, C), the signature MUST include the struct definition with its field names and types (e.g. 'type Cache struct { mu sync.RWMutex; items map[string]any }') so downstream methods know how to access fields without guessing.
5. Target existing repository files rather than inventing new files whenever possible.
6. If test_harness_code tests file reading or external I/O, the test harness MUST create the dummy test file first or use in-memory buffers (e.g. io.BytesIO) so the test does not crash with FileNotFoundError.
7. Each public symbol (function, struct, class) must belong to EXACTLY ONE node. Do not duplicate symbol contracts across multiple nodes in the same package (e.g. Go package main), or the compiler will fail with 'redeclared in this block'. Downstream nodes call upstream functions directly without redeclaring them.
"""




class TopologyResolver:
    """Sanitizes dependencies, prunes ghost references, and computes topological ordering."""

    @classmethod
    def resolve_and_order(cls, graph: TopologyGraph) -> TopologyGraph:
        valid_node_ids = set(graph.nodes.keys())
        G = nx.DiGraph()

        for node_id, node in graph.nodes.items():
            G.add_node(node_id)
            sanitized_deps = []
            for dep in node.dependencies:
                if dep == node_id:
                    continue  # Prune self-loops
                if dep in valid_node_ids:
                    sanitized_deps.append(dep)
                    G.add_edge(dep, node_id)
                # Ghost dependencies (e.g. file paths like 'src/char.cpp' or external modules) are safely ignored
            node.dependencies = sanitized_deps

        if not nx.is_directed_acyclic_graph(G):
            cycles = list(nx.simple_cycles(G))
            raise ValueError(f"TopologyGraph contains circular dependencies: {cycles}")

        graph.execution_order = list(nx.topological_sort(G))
        return graph


class TopologicalPlanner:
    """Level 2 strategic planner managing the invariant DAG."""

    def __init__(self, client: NebiusClient, model: str = LEVEL_2_DEFAULT_MODEL):
        self.client = client
        self.model = model

    def plan(
        self,
        user_prompt: str,
        hard_givens: Optional[Any] = None,
    ) -> TopologyGraph:
        """Generates an invariant DAG from a user request, conditioned on HardGivens."""
        if self.client.mock_mode:
            return self._mock_plan(user_prompt)

        lang = getattr(hard_givens, "target_language", "python") if hard_givens else "python"
        user_content = f"Target Language: {lang}\nRequirement:\n{user_prompt}\n"
        if hard_givens and hard_givens.existing_files:
            user_content += f"Existing files in repository to modify: {', '.join(hard_givens.existing_files)}\n"
            user_content += "CRITICAL: Target these existing files rather than inventing new files whenever possible.\n"
        if hard_givens and hard_givens.boundary_constraints:
            user_content += f"Boundary Constraints: {', '.join(hard_givens.boundary_constraints)}\n"
        user_content += "\nDecompose into a MINIMAL acyclic graph of 1 to 3 micro-goals. Emit valid TopologyGraph JSON."

        messages = [
            {"role": "system", "content": LEVEL_2_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        last_err = None
        for attempt in range(2):
            raw_json = self.client.complete_structured(
                model=self.model,
                messages=messages,
            )
            try:
                return self.parse_and_validate(raw_json)
            except Exception as e:
                last_err = e
                # Re-prompt reminding model to include the 'nodes' dictionary
                messages.append({"role": "assistant", "content": raw_json})
                messages.append({
                    "role": "user",
                    "content": "Your previous response was missing the non-empty 'nodes' dictionary. Emit the complete TopologyGraph JSON with nodes.",
                })

        raise RuntimeError(f"Failed to generate valid TopologyGraph after 2 attempts: {last_err}")

    def parse_and_validate(self, raw_json: str) -> TopologyGraph:
        """Parses raw JSON, validates DAG acyclicity and computes topological ordering."""
        text = raw_json.strip()
        if "```" in text:
            import re
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()
        data = json.loads(text)

        # Handle case where model put JSON in a 'content' field as string
        if isinstance(data.get("content"), str):
            try:
                data = json.loads(data["content"])
            except Exception:
                pass

        # Unwrap if nested under common root keys
        for key in ("graph", "topology", "data", "result", "content"):
            if isinstance(data.get(key), dict) and "nodes" in data[key]:
                data = data[key]
                break

        # Also search for 'nodes' across all top-level values if missing at root
        if "nodes" not in data:
            for v in data.values():
                if isinstance(v, dict) and "nodes" in v:
                    data = v
                    break

        graph = TopologyGraph.model_validate(data)
        return TopologyResolver.resolve_and_order(graph)

    def mutate_subgoal(
        self,
        graph: TopologyGraph,
        failed_subgoal_id: str,
        error_context: str,
    ) -> TopologyGraph:
        """Surgically mutates the DAG when a sub-goal hits an invariant bottleneck."""
        target_node = graph.nodes[failed_subgoal_id]

        # For an automated surgical split: decompose the failed node into two sub-goals
        part1_id = f"{failed_subgoal_id}_core"
        part2_id = f"{failed_subgoal_id}_api"

        # Transfer original contracts split across the new nodes
        contracts = target_node.public_contracts
        split_point = max(1, len(contracts) // 2)

        core_contracts = contracts[:split_point]
        api_contracts = contracts[split_point:] if len(contracts) > 1 else contracts

        node_core = SubGoal(
            id=part1_id,
            module_path=target_node.module_path,
            dependencies=list(target_node.dependencies),
            public_contracts=core_contracts,
            behavioral_invariants=[f"Foundational logic for {failed_subgoal_id}"],
            verification_spec=VerificationSpec(
                test_harness_code="def test_core_smoke():\n    assert True\n"
            ),
        )

        node_api = SubGoal(
            id=part2_id,
            module_path=target_node.module_path,
            dependencies=[part1_id],
            public_contracts=api_contracts,
            behavioral_invariants=list(target_node.behavioral_invariants),
            verification_spec=target_node.verification_spec,
        )

        # Update graph nodes
        del graph.nodes[failed_subgoal_id]
        graph.nodes[part1_id] = node_core
        graph.nodes[part2_id] = node_api

        # Rewire downstream dependencies
        for node in graph.nodes.values():
            if failed_subgoal_id in node.dependencies:
                node.dependencies.remove(failed_subgoal_id)
                node.dependencies.append(part2_id)

        return TopologyResolver.resolve_and_order(graph)

    def _mock_plan(self, prompt: str) -> TopologyGraph:
        """Generates a reference DAG for deterministic testing / offline demonstration."""
        if "go" in prompt.lower():
            node_go = SubGoal(
                id="node_server",
                module_path="server.go",
                dependencies=[],
                public_contracts=[
                    SymbolContract(
                        symbol_name="Server",
                        symbol_type="struct",
                        signature="type Server struct { port int }",
                        docstring="TCP server instance.",
                    )
                ],
                behavioral_invariants=["Must bind port and accept connections"],
                verification_spec=VerificationSpec(syntax_parser="compiler"),
            )
            return TopologyGraph(
                project_summary="Go Server Implementation",
                target_files=["server.go"],
                nodes={"node_server": node_go},
                execution_order=["node_server"],
            )

        node1 = SubGoal(
            id="node_store",
            module_path="cache/store.py",
            dependencies=[],
            public_contracts=[
                SymbolContract(
                    symbol_name="MemoryStore",
                    symbol_type="class",
                    signature="class MemoryStore:\n    def __init__(self):\n    def set(self, key: str, value: str) -> None:\n    def get(self, key: str) -> str | None:",
                    docstring="In-memory key-value storage engine.",
                )
            ],

            behavioral_invariants=[
                "Keys must be strings",
                "Retrieving an unassigned key returns None",
            ],
            verification_spec=VerificationSpec(
                test_harness_code=(
                    "def test_store_invariants():\n"
                    "    store = MemoryStore()\n"
                    "    assert store.get('k') is None\n"
                    "    store.set('k', 'v')\n"
                    "    assert store.get('k') == 'v'\n"
                )
            ),
        )

        node2 = SubGoal(
            id="node_cache",
            module_path="cache/lru.py",
            dependencies=["node_store"],
            public_contracts=[
                SymbolContract(
                    symbol_name="LRUCache",
                    symbol_type="class",
                    signature="class LRUCache:\n    def __init__(self, capacity: int = 10):\n    def put(self, key: str, value: str) -> None:\n    def get(self, key: str) -> str | None:",
                    docstring="LRU Cache with bounded capacity.",
                )
            ],
            behavioral_invariants=[
                "Capacity must be respected, evicting oldest item on overflow",
            ],
            verification_spec=VerificationSpec(
                test_harness_code=(
                    "def test_lru_invariants():\n"
                    "    cache = LRUCache(capacity=2)\n"
                    "    cache.put('a', '1')\n"
                    "    cache.put('b', '2')\n"
                    "    assert cache.get('a') == '1'\n"
                    "    cache.put('c', '3')\n"
                    "    assert cache.get('b') is None\n"
                    "    assert cache.get('c') == '3'\n"
                )
            ),
        )

        return TopologyGraph(
            project_summary="LRU Cache with In-Memory Storage",
            target_files=["cache/store.py", "cache/lru.py"],
            nodes={"node_store": node1, "node_cache": node2},
            execution_order=["node_store", "node_cache"],
        )
