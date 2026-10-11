"""Ponder Pipeline Orchestrator."""

from __future__ import annotations
from typing import Callable, Dict, List, Optional
from ponder.actuator import SemanticActuator
from ponder.assembler import WorkspaceAssembler
from ponder.client import NebiusClient
from ponder.givens import HardGivensExtractor
from ponder.models import ChunkOutput, HardGivens, SubGoal, SymbolContract, TopologyGraph, VerificationResult
from ponder.planner import TopologicalPlanner
from ponder.verifier import VerificationGate


class Orchestrator:
    """End-to-end Ponder execution coordinator."""

    def __init__(
        self,
        workspace_dir: str,
        client: Optional[NebiusClient] = None,
        max_chunk_retries: int = 4,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ):
        self.workspace_dir = workspace_dir
        self.client = client or NebiusClient()
        self.max_chunk_retries = max_chunk_retries
        self.on_event = on_event or (lambda event, data: None)

        self.givens_extractor = HardGivensExtractor(self.client)
        self.planner = TopologicalPlanner(self.client)
        self.actuator = SemanticActuator(self.client)
        self.verifier = VerificationGate()
        self.assembler = WorkspaceAssembler(self.workspace_dir)

    def run(self, requirement: str) -> Dict[str, str]:
        """Executes requirement through Hard Givens, Level 2 planning, Level 1 actuation, and Polyglot Verification."""
        self.on_event("planning_start", {"requirement": requirement})

        # 0. Level 3 Invariant Anchor: Extract and freeze Hard Givens
        hard_givens = self.givens_extractor.extract(requirement, workspace_dir=self.workspace_dir)
        self.on_event("givens_complete", {
            "target_language": hard_givens.target_language,
            "protocols": hard_givens.protocols_and_specs,
            "acceptance_criteria": hard_givens.acceptance_criteria,
            "compile_cmd": hard_givens.toolchain.compile_cmd,
            "test_cmd": hard_givens.toolchain.test_cmd,
        })

        # 1. Level 2 Macro-Topological Planning
        graph = self.planner.plan(requirement, hard_givens=hard_givens)
        self.on_event("planning_complete", {
            "summary": graph.project_summary,
            "execution_order": graph.execution_order,
            "node_count": len(graph.nodes),
            "nodes": {
                nid: {
                    "id": n.id,
                    "module_path": n.module_path,
                    "dependencies": n.dependencies,
                    "contracts": [c.symbol_name for c in n.public_contracts],
                    "invariants": n.behavioral_invariants,
                    "status": n.status,
                }
                for nid, n in graph.nodes.items()
            },
        })

        verified_chunks: Dict[str, ChunkOutput] = {}

        verified_chunks: Dict[str, ChunkOutput] = {}

        # 2. Topological Level-by-Level Execution with Fail-Fast Cancellation
        import networkx as nx
        from concurrent.futures import ThreadPoolExecutor, as_completed

        G = nx.DiGraph()
        for node_id, node in graph.nodes.items():
            G.add_node(node_id)
            for dep in node.dependencies:
                G.add_edge(dep, node_id)

        generations = list(nx.topological_generations(G))

        for gen_idx, generation in enumerate(generations):
            is_final = (gen_idx == len(generations) - 1)
            if len(generation) == 1:
                subgoal_id = generation[0]
                success, chunk, err = self._execute_subgoal(
                    subgoal_id=subgoal_id,
                    graph=graph,
                    hard_givens=hard_givens,
                    is_final_subgoal=is_final,
                )
                if success and chunk:
                    verified_chunks[subgoal_id] = chunk
                else:
                    self._abort_downstream(generations[gen_idx + 1:], graph)
                    return {
                        "status": "failed",
                        "error": f"SubGoal '{subgoal_id}' failed verification: {err}",
                        "verified_subgoals": list(verified_chunks.keys()),
                    }
            else:
                # Parallel execution of independent subgoals within the same generation
                failed_id = None
                failed_err = None
                with ThreadPoolExecutor(max_workers=min(len(generation), 4)) as executor:
                    future_to_id = {
                        executor.submit(
                            self._execute_subgoal,
                            nid,
                            graph,
                            hard_givens,
                            is_final,
                        ): nid
                        for nid in generation
                    }
                    for future in as_completed(future_to_id):
                        nid = future_to_id[future]
                        try:
                            success, chunk, err = future.result()
                            if success and chunk:
                                verified_chunks[nid] = chunk
                            else:
                                failed_id = nid
                                failed_err = err
                        except Exception as e:
                            failed_id = nid
                            failed_err = str(e)

                if failed_id:
                    self._abort_downstream(generations[gen_idx + 1:], graph)
                    return {
                        "status": "failed",
                        "error": f"SubGoal '{failed_id}' failed verification: {failed_err}",
                        "verified_subgoals": list(verified_chunks.keys()),
                    }

        # 3. Workspace Assembly
        written_files = self.assembler.assemble(graph.nodes, verified_chunks)
        self.on_event("assembly_complete", {"files": written_files})

        # 4. Final End-to-End Acceptance Verification
        if hard_givens.toolchain.test_cmd:
            final_res = self.verifier.run_toolchain_command(
                cmd=hard_givens.toolchain.test_cmd,
                cwd=self.workspace_dir,
                target_lang=hard_givens.target_language,
            )
            if not final_res.passed:
                err_str = final_res.error_message or ""
                if not any(k in err_str for k in ("no test files", "no packages to test", "[no test files]", "collected 0 items", "no tests ran")):
                    self.on_event("verification_fail", {
                        "stage": "final_acceptance",
                        "error": err_str,
                    })
                    return {
                        "status": "failed",
                        "error": f"Final acceptance suite failed: {err_str}",
                        "files": written_files,
                        "verified_subgoals": list(verified_chunks.keys()),
                    }

        return {
            "status": "success",
            "files": written_files,
            "verified_subgoals": list(verified_chunks.keys()),
        }

    def _execute_subgoal(
        self,
        subgoal_id: str,
        graph: TopologyGraph,
        hard_givens: HardGivens,
        is_final_subgoal: bool = True,
    ) -> tuple[bool, Optional[ChunkOutput], str]:
        """Synthesizes, verifies, and repairs an individual subgoal."""
        subgoal = graph.nodes[subgoal_id]
        self.on_event("subgoal_start", {
            "subgoal_id": subgoal_id,
            "module_path": subgoal.module_path,
            "dependencies": subgoal.dependencies,
        })

        # Extract prerequisite contracts ONLY (zero implementation code leakage)
        prereq_contracts: List[SymbolContract] = []
        for dep_id in subgoal.dependencies:
            if dep_id in graph.nodes:
                prereq_contracts.extend(graph.nodes[dep_id].public_contracts)

        last_error = ""
        current_chunk: Optional[ChunkOutput] = None

        for attempt in range(1, self.max_chunk_retries + 2):
            subgoal.attempts = attempt
            self.on_event("chunk_attempt", {
                "subgoal_id": subgoal_id,
                "attempt": attempt,
                "max_retries": self.max_chunk_retries + 1,
                "module_path": subgoal.module_path,
            })

            if attempt == 1:
                current_chunk = self.actuator.synthesize(
                    subgoal=subgoal,
                    dependency_contracts=prereq_contracts,
                    hard_givens=hard_givens,
                    workspace_dir=self.workspace_dir,
                )
            else:
                assert current_chunk is not None
                current_chunk = self.actuator.repair(
                    subgoal=subgoal,
                    failed_chunk=current_chunk,
                    error_log=last_error,
                    dependency_contracts=prereq_contracts,
                    hard_givens=hard_givens,
                    workspace_dir=self.workspace_dir,
                )

            self.on_event("code_emitted", {
                "subgoal_id": subgoal_id,
                "attempt": attempt,
                "module_path": subgoal.module_path,
                "code": current_chunk.code,
                "line_count": len(current_chunk.code.splitlines()),
            })

            # Discrete Polyglot Verification Gate
            verif_res: VerificationResult = self.verifier.verify(
                subgoal=subgoal,
                chunk=current_chunk,
                upstream_contracts=prereq_contracts,
                hard_givens=hard_givens,
                workspace_dir=self.workspace_dir,
                is_final_subgoal=is_final_subgoal,
            )

            if verif_res.passed:
                subgoal.status = "verified"
                self.on_event("verification_pass", {
                    "subgoal_id": subgoal_id,
                    "attempt": attempt,
                    "stage": verif_res.stage,
                })
                return True, current_chunk, ""
            else:
                last_error = verif_res.error_message or "Unknown verification error"
                self.on_event("verification_fail", {
                    "subgoal_id": subgoal_id,
                    "stage": verif_res.stage,
                    "error": last_error,
                    "attempt": attempt,
                })

        # Retries exhausted
        self.on_event("bottleneck_detected", {
            "subgoal_id": subgoal_id,
            "error": last_error,
        })
        return False, None, last_error

    def _abort_downstream(self, remaining_generations: List[List[str]], graph: TopologyGraph):
        """Immediately marks all doomed downstream nodes as failed to save tokens and time."""
        for gen in remaining_generations:
            for nid in gen:
                if nid in graph.nodes:
                    graph.nodes[nid].status = "failed"
                    self.on_event("subgoal_aborted", {
                        "subgoal_id": nid,
                        "reason": "Prerequisite ancestor failed verification. Aborted to save tokens.",
                    })
