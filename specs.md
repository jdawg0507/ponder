# Specification: Ponder - Contract-Gated Topological Coding Agent

## 1. Overview & Core Philosophy

Standard software engineering agents suffer from autoregressive drift: errors in early conversational turns cascade into hallucinations, altered interfaces, and invalid global states.

Ponder addresses this by departing from monolithic autoregressive loops in favor of a **Contract-Gated Topological Architecture** (conceptually inspired by multi-scale hierarchical planning):
- **Level 3 (Invariant Anchor):** Freezes non-negotiable toolchains, language runtimes, and protocol constraints before planning.
- **Level 2 (Macro-Topological Planner):** Operates strictly on the structural dependency graph of the codebase (contracts, interfaces, state boundaries, DAG dependencies). Level 2 is strictly forbidden from writing implementation code.
- **Level 1 (Semantic Chunk Actuator):** Synthesizes bounded, isolated execution units conditioned strictly on the lightweight contracts emitted by Level 2—eliminating full-codebase context dumps.
- **Discrete Verification Gate:** Validates contract satisfaction and compilation deterministically via AST parsing, type checking, and isolated unit tests before committing to the workspace.

```
                  ┌──────────────────────────────┐
                  │ User Request / Specification │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │       LEVEL 3: INVARIANT ANCHOR (HARD GIVENS)  │
         │   Freezes Language, Toolchain, Wire Protocols  │
         └───────────────────────┬────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │       LEVEL 2: STRATEGIC TOPOLOGY PLANNER      │
         │      Conditioned strictly on Hard Givens       │
         └───────────────────────┬────────────────────────┘
                                 │
                 Emits TopologyGraph (Acyclic DAG)
            (Symbol Contracts, Invariants, Test Specs)
                                 │
                                 ▼
                     [Topological Node Queue]
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               │ (Next node)
         ┌────────────────────────────────┐      │
         │  LEVEL 1: SEMANTIC ACTUATOR    │◄─────┘
         │  (Polyglot Realization:        │
         │   Rust, Go, TypeScript, Python)│
         └───────────────┬────────────────┘
                         │
                 Emits Realized Source Chunk
                         │
                         ▼
         ┌────────────────────────────────┐
         │   POLYGLOT VERIFICATION GATE   │
         │  (cargo check/test, go build,  │
         │   ast.parse, codecrafters test)│
         └───────────────┬────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
       [PASS]                        [FAIL]
  Commit Node to Workspace      Attempts <= 2: Retry Level 1 with error log
  Advance Dependency Pointer    Attempts > 2:  Level 2 Surgical Graph Mutation
```


---

## 2. Model Selection & Roles

| Component | Target Model | Provider / Endpoint | Role |
| :--- | :--- | :--- | :--- |
| **Level 2 (Planner)** | `meta-llama/Meta-Llama-3.1-70B-Instruct` | Nebius Token Factory (`https://api.tokenfactory.nebius.com/v1`) | Generates DAG, contracts, pre/post-conditions, and test harnesses. Emits JSON schema only. |
| **Level 2 (Escalation)** | `meta-llama/Meta-Llama-3.1-405B-Instruct` | Nebius Token Factory | Fallback planner for complex DAG replanning / deadlock resolution. |
| **Level 1 (Actuator)** | `Qwen/Qwen2.5-Coder-32B-Instruct` | Nebius Token Factory | Generates code within bounded AST scope. Zero conversational memory. |
| **Verification Gate** | Deterministic Tooling (Python `ast`, `mypy`/`pyright`, `pytest`) | Local runtime | Deterministic gate validating syntax, types, and invariant test harnesses. |

---

## 3. Data Contracts & Schemas

### 3.1 SymbolContract
Defines the public export surface that Level 1 must satisfy. Level 1 cannot alter symbol names, parameters, type annotations, or return types.

```python
from typing import List, Literal
from pydantic import BaseModel, Field

class SymbolContract(BaseModel):
    symbol_name: str
    symbol_type: Literal["function", "class", "async_function"]
    signature: str
    docstring: str
    raises: List[str] = Field(default_factory=list)
```

### 3.2 VerificationSpec
Defines deterministic checks executed before a chunk is accepted into the workspace.

```python
class VerificationSpec(BaseModel):
    syntax_parser: Literal["python_ast", "tree_sitter"] = "python_ast"
    type_stubs_required: List[str] = Field(default_factory=list)
    test_harness_code: str  # Standalone executable test exercising the invariant
```

### 3.3 SubGoal (DAG Node)
The fundamental atomic unit of planning and execution.

```python
class SubGoal(BaseModel):
    id: str
    module_path: str                        # Target file (e.g. "src/storage/kv.py")
    dependencies: List[str]                 # IDs of prerequisite sub-goals
    public_contracts: List[SymbolContract]  # Immutable public surface
    private_scope_allowed: bool = True      # Whether Level 1 may introduce `_` helpers
    behavioral_invariants: List[str]        # Plain-English and logical rules
    verification_spec: VerificationSpec
    status: Literal["pending", "verifying", "verified", "failed"] = "pending"
```

### 3.4 TopologyGraph
The Level 2 output representation.

```python
from typing import Dict

class TopologyGraph(BaseModel):
    project_summary: str
    target_files: List[str]
    nodes: Dict[str, SubGoal]
    execution_order: List[str]              # Topologically sorted node IDs
```

### 3.5 ChunkOutput
The Level 1 emission.

```python
class ChunkOutput(BaseModel):
    subgoal_id: str
    code: str                               # Realized Python code
    imports: List[str]                      # Required import statements
```

---

## 4. Execution Lifecycle

```
[User Input]
     │
     ▼
Phase A: Macro Planning
     1. Level 2 generates TopologyGraph JSON.
     2. Graph validator asserts acyclicity via networkx.
     3. Topological sort determines execution queue.
     │
     ▼
Phase B: Chunk Actuation Loop (Per SubGoal in topological order)
     1. Context Isolator extracts:
        - Target SubGoal specification.
        - Public contracts of upstream dependencies (NO implementation code).
     2. Level 1 synthesizes ChunkOutput.
     │
     ▼
Phase C: Discrete Verification Gate
     1. Syntax Check: ast.parse(chunk.code) must succeed.
     2. Signature Match: ast inspection verifies all public_contracts exist with exact signatures.
     3. Virtual Type Check: Generate in-memory .pyi stubs of dependencies and run mypy.
     4. Dynamic Test: Execute test_harness_code against realized chunk in an isolated runner.
     │
     ├─► PASS: Commit chunk to workspace memory, advance pointer to next SubGoal.
     │
     └─► FAIL:
          ├─► Attempt count <= 2:
          │     Send compiler/test error to Level 1 for isolated repair.
          │
          └─► Attempt count > 2 (Invariant Bottleneck):
                Trigger Level 2 Surgical Graph Mutation:
                - SPLIT_NODE: break node into smaller primitives.
                - REVISE_CONTRACT: adjust or relax preconditions.
                - Re-evaluate downstream affected edges only.
     │
     ▼
Phase D: Workspace Assembly
     1. Merge verified AST nodes into target files.
     2. Deduplicate imports.
     3. Format with ruff / black.
```

---

## 5. Context Isolation Rules

To prevent autoregressive drift and token bloat:
1. **Zero Conversational History:** Level 1 prompts never receive past user-assistant conversational turns.
2. **Contract-Only Visibility:** Level 1 cannot view the internal source code of completed dependencies—only their `SymbolContract` stubs.
3. **Public Surface Immutability:** Any modification to a signature defined in `SymbolContract` results in immediate gate rejection.
4. **Private Implementation Scope:** Level 1 may define private helper functions (prefixed with `_`) and local classes as needed to fulfill the contract.

---

## 6. Failure Modes & Mitigations

| Failure Mode | Mechanism | Mitigation |
| :--- | :--- | :--- |
| **Autoregressive Drift** | Early hallucinated interface propagated into subsequent tokens. | Level 2 emits immutable signatures; Level 1 receives only contracts of prerequisite nodes. |
| **Context Bloat ($O(N^2)$)** | Full codebase repeatedly fed to LLM in chat window. | Strict $O(1)$ context window per SubGoal execution. |
| **Isolated Type Errors** | Running static type checker on an isolated chunk fails due to missing external imports. | Ephemeral Virtual Environment synthesizes `.pyi` type stubs in memory for all Level 2 contracts. |
| **Invariant Bottleneck** | A required dependency is mathematically or structurally unsatisfiable. | Topologically ordered execution halts before downstream tokens are generated; Level 2 surgical replanning triggers. |
| **Markdown Chatter** | Actuator emits conversational text instead of clean code. | Nebius JSON schema enforcement and strict AST code extraction delimiters. |

---

## 7. Verification Gate Pipeline

```python
# Verification Gate Execution Flow
def verify_chunk(subgoal: SubGoal, chunk: ChunkOutput, virtual_env: VirtualStubEnv) -> VerificationResult:
    # 1. AST Syntax Check
    tree = parse_ast(chunk.code)
    
    # 2. Signature Concordance Check
    validate_signatures(tree, subgoal.public_contracts)
    
    # 3. Static Type Verification against Virtual Stubs
    type_check_result = virtual_env.typecheck(chunk)
    if not type_check_result.success:
        return VerificationResult(passed=False, error=type_check_result.stderr)
        
    # 4. Invariant Test Harness Execution
    test_result = run_isolated_test(chunk, subgoal.verification_spec.test_harness_code)
    if not test_result.passed:
        return VerificationResult(passed=False, error=test_result.error)
        
    return VerificationResult(passed=True)
```
