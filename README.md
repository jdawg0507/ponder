# Ponder: Contract-Gated Topological Coding Agent

A deterministic, contract-driven software synthesis engine that decomposes complex engineering specifications into acyclic dependency graphs, enforces immutable interface boundaries, and actuates isolated code generation across polyglot codebases.

Built to outperform monolithic autoregressive coding agents on demanding benchmarks like CodeCrafters (CCBench) through topological parallelism, contract isolation, and discrete compiler-gated verification.

---

## "Wait, is this technically H-JEPA?" (No — and why that's a good thing)

The project originally drew inspiration from Yann LeCun's **Hierarchical Joint Embedding Predictive Architecture (H-JEPA)**: the concept of predicting abstract representations at multiple temporal and hierarchical scales rather than predicting every low-level token autoregressively.

However, **Ponder is not literally H-JEPA** in the machine learning sense:
- **Literal H-JEPA** operates entirely on continuous latent vector embeddings. It predicts target representations $s_y = \text{Enc}(y)$ from context $s_x = \text{Enc}(x)$ using energy-based loss functions in embedding space, deliberately eschewing generative decoding or token synthesis.
- **Software engineering is fundamentally discrete, symbolic, and executable.** Code cannot remain an abstract vector embedding; it must compile, link, satisfy concrete type systems, pass AST parsing, and execute deterministic tests.

### What we actually built: A Contract-Gated Topological Agent

Instead of forcing continuous embeddings onto source code, we adapted the core principle—**multi-scale hierarchical planning with strict invariant boundaries**—into a practical software synthesis architecture:

1. **Level 3 (Invariant Anchor):** Freezes environmental invariants (compilers, build systems, target versions, wire protocols) before planning begins.
2. **Level 2 (Macro-Topological Planner):** Operates purely in the structural contract space (synthesizing an acyclic directed graph of symbol contracts, type signatures, and behavioral invariants). Level 2 is strictly forbidden from writing implementation code.
3. **Level 1 (Semantic Leaf Actuator):** Synthesizes bounded, isolated implementation files conditioned *strictly* on prerequisite interface contracts—never on full-codebase context dumps.
4. **Discrete Verification Gate:** Uses real compilers and test harnesses as a discrete energy function $E(x, y) \in \{0, >0\}$ to enforce invariant compliance before workspace merge.

### Why this is dramatically more efficient than standard agents

By departing from both monolithic chat agents and theoretical continuous latent predictors, Ponder achieves practical efficiency advantages:

| Dimension | Monolithic LLM Agents (ReAct / Claude Code / Devin style) | Ponder (Contract-Gated Topological) |
| :--- | :--- | :--- |
| **Context Window Scaling** | $O(N \cdot \text{turns})$: Accumulates entire files, tool dumps, and noisy history (30k–100k+ tokens). | **$O(1)$ Contract Isolation**: Actuators only see immediate prerequisite `SymbolContract` interfaces (~200–500 tokens). |
| **Error Propagation** | **Cascading drift**: A bug or hallucinated import in turn 2 corrupts turns 3 through 20. | **Zero cross-module leakage**: Failures are isolated to the leaf node and healed via local repair loops. |
| **Execution Concurrency** | **Serial**: Every step blocks on the previous conversational turn. | **Topological Parallelism**: Independent DAG layers execute concurrently across worker threads. |
| **Verification Reliability** | "Self-reflection" prompts where the LLM guesses whether its own code works. | **Deterministic Toolchain Gates**: Real compiler passes (`cargo check`, `go build`, `ast.parse`) gate acceptance. |
| **Token Cost & Latency** | High token burn per iteration due to repeated global context re-ingestion. | Minimal token consumption; sub-3-second planning with targeted leaf generation. |

---

## Architecture Overview

```
                           ┌──────────────────────────────┐
                           │ User Request / Specification │
                           └──────────────┬───────────────┘
                                          │
                                          ▼
                   ┌──────────────────────────────────────────────┐
                   │          LEVEL 3: INVARIANT ANCHOR           │
                   │  (Freezes Hard Givens, Toolchains & Specs)   │
                   └──────────────────────┬───────────────────────┘
                                          │ Hard Givens Constraints
                                          ▼
                   ┌──────────────────────────────────────────────┐
                   │      LEVEL 2: MACRO-TOPOLOGICAL PLANNER      │◄────────────────┐
                   │    (Synthesizes Acyclic Invariant DAG)       │                 │
                   └──────────────────────┬───────────────────────┘                 │
                                          │ TopologyGraph                           │
                                          ▼                                         │
                   ┌──────────────────────────────────────────────┐                 │
                   │     Topological Scheduler & Generations      │                 │
                   │     Queue (Parallel Independent Nodes)       │                 │
                   └──────────────────────┬───────────────────────┘                 │
                                          │ SubGoal + Prereq Contracts              │
                                          ▼                                         │
                        ┌───────────────────────────────────┐                       │
                        │    LEVEL 1: SEMANTIC ACTUATOR     │◄─────────┐            │
                        │   (Isolated AST Chunk Synthesis)  │          │            │
                        └─────────────────┬─────────────────┘          │            │
                                          │ Synthesized Code           │            │
                                          ▼                            │            │
                        ┌───────────────────────────────────┐          │            │
                        │    DISCRETE VERIFICATION GATE     │          │            │
                        │  Deterministic Energy Loss E(x, y)│          │            │
                        └─────────────────┬─────────────────┘          │            │
                                          │                            │            │
                 ┌────────────────────────┴────────────────────────┐   │            │
                 ▼                                                 ▼   │            │
         [E(x,y) = 0: PASS]                                [E(x,y) > 0: FAIL]       │
                 │                                                 │                │
                 │                                        Attempts <= Retries       │
                 │                                        └───► [Turn Repair Loop] ─┘
                 │                                        Attempts > Retries
                 │                                        └─────► [Surgical DAG Mutation]
                 ▼
 ┌─────────────────────────────────────────────────┐
 │               WORKSPACE ASSEMBLER               │
 │     (Atomic Merge & Preserved File Headers)     │
 └────────────────────────┬────────────────────────┘
                          │
                          ▼
 ┌─────────────────────────────────────────────────┐
 │        FINAL ACCEPTANCE VERIFICATION            │
 │     (End-to-End Test Suite Execution)           │
 └─────────────────────────────────────────────────┘
```

### 1. Level 3: Invariant Anchor
- Extracts and freezes immutable constraints (**Hard Givens**): target language, build systems, compiler flags, and wire protocols.
- Prevents downstream drift, toolchain mismatch, and hallucinated runtimes.

### 2. Level 2: Macro-Topological Planner
- Decomposes high-level requirements into an acyclic directed graph (DAG) of atomic sub-goals.
- Generates strict `SymbolContract` boundaries (signatures, types, behavioral invariants) with zero implementation code leakage.
- Driven by `Qwen/Qwen3-30B-A3B-Instruct-2507` on Nebius Token Factory for sub-3-second planning latency.

### 3. Level 1: Semantic Chunk Actuator
- Implements individual sub-goals in pure isolation, conditioned strictly on prerequisite symbol contracts.
- 8,192 token output headroom to guarantee full file synthesis without truncation.
- Context-aware repair loop feeding compiler diagnostics directly into targeted syntax recovery.

### 4. Polyglot Verification Gate
- Executes deterministic verification across Go, Rust, C++, Python, and Java.
- **Docker / OrbStack Sandboxing:** Containerized toolchains (`golang:alpine`, `rust:slim`, `gcc:latest`, `openjdk:17-slim`) when local host compilers are absent.
- **Compiler Cache Isolation:** Injects project-local caches (`GOCACHE`, `CARGO_TARGET_DIR`, `CCACHE_DIR`) under `.cache/`.
- **Auto-Healing:** Instant regex auto-removal of unused imports in Go to prevent fatal compilation halts.
- **Staged Verification:** Intermediate microsteps are checked for compilation and contract compliance, while end-to-end acceptance tests gate final assembly.

---

## Features

- **CodeCrafters Benchmark Harness (CCBench):** Integrated evaluation runner for official CodeCrafters challenges (Redis, Git, SQLite, Grep, Shell, etc.).
- **Live Real-Time WebUI:** FastAPI backend with Server-Sent Events (SSE) and glassmorphic UI (`/ui`) for monitoring live DAG progress, compiler logs, and pass rates.
- **Topological Parallelism:** Automatically executes independent generation layers in parallel using thread workers, with fail-fast cancellation to prevent token waste on failed dependencies.

---

## Quickstart

### 1. Installation
Clone the repository and install dependencies using `uv` or standard Python:

```bash
uv pip install -e .
# or
pip install -e .
```

### 2. Configure Environment
Set your Nebius Token Factory API key in `.env`:

```bash
NEBIUS_API_KEY="your-token-factory-key"
LEVEL_2_MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507"
LEVEL_1_MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507"
```

### 3. Run Tests
Verify all unit, integration, and orchestration tests:

```bash
PYTHONPATH=. .venv/bin/pytest -v tests
```

### 4. Launch the Web Dashboard & Server
```bash
PYTHONPATH=. .venv/bin/python -m ponder.server
```
Visit `http://localhost:8000/ui` to track live runs and benchmarks.

### 5. Run the Benchmark Suite via CLI
```bash
# Run benchmark tasks with parallel execution
PYTHONPATH=. .venv/bin/python -m ponder.benchmarks.ccbench --parallel 2
```

---

## Project Layout

```
ponder/
├── ponder/
│   ├── actuator.py          # Level 1 AST Chunk Synthesizer & Repair
│   ├── assembler.py         # Multi-file Workspace Assembler
│   ├── client.py            # Nebius Token Factory Client
│   ├── givens.py            # Level 3 Hard Givens Extractor
│   ├── models.py            # Pydantic Schemas & Symbol Contracts
│   ├── orchestrator.py      # Topologically parallel execution coordinator
│   ├── planner.py           # Level 2 Macro-Topological Planner (DAG)
│   ├── server.py            # FastAPI Daemon & Event Streaming
│   ├── verifier.py          # Polyglot compiler & container gate
│   ├── benchmarks/
│   │   └── ccbench.py       # CodeCrafters benchmark adapter
│   └── ui/
│       └── index.html       # Real-time WebUI Dashboard
├── tests/                   # Pytest suite
├── AGENTS.md                # Operating instructions for coding agents
├── specs.md                 # Technical specification document
└── README.md
```

---

## License

MIT
