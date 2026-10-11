"""Level 1 Semantic Chunk Actuator for Ponder Coding Agent."""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from ponder.client import LEVEL_1_DEFAULT_MODEL, NebiusClient
from ponder.diagnostics import DiagnosticAnalyzer
from ponder.languages import LanguageRegistry
from ponder.models import ChunkOutput, SubGoal, SymbolContract


LEVEL_1_SYSTEM_PROMPT = """You are the Level 1 Semantic Code Actuator in the Ponder Coding Agent architecture.
We are building a robust coding agent: a strategic planning stage decomposes complex engineering requirements into clear, atomic microsteps, contracts, and invariants so you can implement each step with precision.
Your duty is to generate executable, production-ready, fully compilable code that strictly satisfies the provided SubGoal, HardGivens, and SymbolContracts.

CRITICAL INVARIANTS:
1. The code must be complete and fully compilable. Do not leave placeholder comments, ellipsis `...`, or unfinished function bodies.
2. If starter code or an existing file is provided, update or complete the entire file cleanly, keeping package declarations, imports, and surrounding code intact so the whole file compiles.
3. Exported public symbols must EXACTLY match the provided SymbolContracts (names, arguments, types).
4. Emit valid code within a ```<language> ... ``` markdown block.
5. DO NOT provide conversational introductions, commentary, or explanations. Emit ONLY the code.
"""


class SemanticActuator:
    """Level 1 worker synthesizing isolated AST chunks."""

    def __init__(self, client: NebiusClient, model: str = LEVEL_1_DEFAULT_MODEL):
        self.client = client
        self.model = model

    def synthesize(
        self,
        subgoal: SubGoal,
        dependency_contracts: List[SymbolContract],
        hard_givens: Optional[Any] = None,
        workspace_dir: Optional[str] = None,
    ) -> ChunkOutput:
        """Synthesizes code for a subgoal conditioned on minimal contract context and existing files."""
        if self.client.mock_mode:
            return self._mock_synthesize(subgoal)

        prompt = self._build_prompt(subgoal, dependency_contracts, hard_givens, workspace_dir)
        messages = [
            {"role": "system", "content": LEVEL_1_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        raw_output = self.client.complete_code(
            model=self.model,
            messages=messages,
        )

        return self._extract_chunk(subgoal.id, raw_output)

    def repair(
        self,
        subgoal: SubGoal,
        failed_chunk: ChunkOutput,
        error_log: str,
        dependency_contracts: List[SymbolContract],
        hard_givens: Optional[Any] = None,
        workspace_dir: Optional[str] = None,
    ) -> ChunkOutput:
        """Repairs candidate code using the exact verification failure log."""
        if self.client.mock_mode:
            # If in mock mode, return corrected reference code
            return self._mock_synthesize(subgoal)

        lang = getattr(hard_givens, "target_language", "python") if hard_givens else "python"
        prompt_parts = [
            f"The candidate code for SubGoal '{subgoal.id}' in '{subgoal.module_path}' failed verification.\n",
            f"### Target Language: {lang}",
            f"### Target Module: {subgoal.module_path}\n",
            f"### Failed Code:\n```{lang}\n{failed_chunk.code}\n```\n",
            f"### Verification Error / Compiler Output:\n{error_log}\n",
        ]
        if subgoal.verification_spec and subgoal.verification_spec.test_harness_code:
            prompt_parts.append(f"### Failing Test Harness:\n```{lang}\n{subgoal.verification_spec.test_harness_code}\n```\n")
        prompt_parts.extend([
            f"### Public Contracts Required:\n{self._format_contracts(subgoal.public_contracts)}\n",
            f"Fix the error while strictly preserving all SymbolContracts and ensuring the file compiles cleanly.",
            f"IMPORTANT: Include package declarations, all required imports (e.g. fmt, os, strings), and surrounding functions.",
        ])
        diagnostic = DiagnosticAnalyzer.analyze(error_log, lang)
        if diagnostic.remediation_directive:
            prompt_parts.append(f"### Diagnostic Remediation:\n{diagnostic.remediation_directive}\n")
        prompt_parts.append(
            f"Emit the complete, compilable {lang} source code inside ```{lang} ... ``` markdown fences only."
        )
        prompt = "\n".join(prompt_parts)

        messages = [
            {"role": "system", "content": LEVEL_1_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        raw_output = self.client.complete_code(
            model=self.model,
            messages=messages,
        )
        return self._extract_chunk(subgoal.id, raw_output)

    def _build_prompt(
        self,
        subgoal: SubGoal,
        dependency_contracts: List[SymbolContract],
        hard_givens: Optional[Any] = None,
        workspace_dir: Optional[str] = None,
    ) -> str:
        lang = getattr(hard_givens, "target_language", "python") if hard_givens else "python"
        prompt_lines = [
            f"Target Language: {lang}",
            f"Target Module: {subgoal.module_path}",
            f"SubGoal ID: {subgoal.id}",
        ]

        if hard_givens:
            if hard_givens.protocols_and_specs:
                prompt_lines.append(f"Protocols & Specs: {', '.join(hard_givens.protocols_and_specs)}")
            if hard_givens.allowed_dependencies:
                prompt_lines.append(f"Allowed Dependencies: {', '.join(hard_givens.allowed_dependencies)}")

        # Include existing file content if available in workspace
        if workspace_dir:
            target_path = Path(workspace_dir) / subgoal.module_path
            if target_path.exists():
                try:
                    existing_text = target_path.read_text(encoding="utf-8")
                    if existing_text.strip():
                        prompt_lines.append(f"\n### Existing File Content ({subgoal.module_path}):")
                        prompt_lines.append(f"```{lang}\n{existing_text}\n```")
                        prompt_lines.append(
                            "CRITICAL: Update/complete this file while keeping existing valid package headers, imports, and functions intact. "
                            "The resulting code must be the entire compilable file."
                        )
                except Exception:
                    pass

        prompt_lines.extend([
            "\n### Public Contracts Required:",
            self._format_contracts(subgoal.public_contracts),
            "\n### Behavioral Invariants:",
        ])
        for inv in subgoal.behavioral_invariants:
            prompt_lines.append(f"- {inv}")

        if dependency_contracts:
            prompt_lines.append("\n### Available Upstream Dependency Contracts (Interface Only):")
            prompt_lines.append(self._format_contracts(dependency_contracts))

        profile = LanguageRegistry.get(lang or subgoal.module_path)
        scope_directive = profile.get_scope_directive()
        if scope_directive:
            prompt_lines.append(f"\n### Language Scope Invariant:\n{scope_directive}")

        prompt_lines.append(
            f"\nEmit only the complete, production-ready {lang} code for this file within ```{lang} ... ``` fences. "
            "Include the package declaration (e.g. 'package main' if applicable), all necessary imports, and all required symbols."
        )

        return "\n".join(prompt_lines)

    def _format_contracts(self, contracts: List[SymbolContract]) -> str:
        out = []
        for c in contracts:
            out.append(f"Symbol: {c.symbol_name} ({c.symbol_type})")
            out.append(f"Signature:\n{c.signature}")
            if c.docstring:
                out.append(f"Docstring: {c.docstring}")
            out.append("")
        return "\n".join(out)

    def _extract_chunk(self, subgoal_id: str, raw_text: str) -> ChunkOutput:
        """Extracts source code from any language markdown fence or raw text."""
        # Strip any thinking tags if present
        clean_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()
        code_match = re.search(r"`{3,}(?:\w+)?\s*([\s\S]*?)`{3,}", clean_text)
        if code_match:
            code = code_match.group(1).strip()
        else:
            code = clean_text.strip()

        # Strip any stray leading or trailing backticks
        code = re.sub(r"^`+", "", code).strip()
        code = re.sub(r"`+$", "", code).strip()

        # Strip stray language identifier line (e.g. 'go', 'python') if model leaked it as first line
        lines = code.splitlines()
        known_langs = {"go", "golang", "python", "py", "rust", "rs", "cpp", "c++", "c", "java", "typescript", "ts", "javascript", "js", "sh", "bash"}
        if lines and lines[0].strip().lower() in known_langs:
            code = "\n".join(lines[1:]).strip()

        # For Go source files, ensure we do not have stray text before the package declaration
        if "package " in code:
            pkg_idx = code.find("package ")
            prefix = code[:pkg_idx].strip()
            if prefix and not all(p.strip().startswith("//") or p.strip().startswith("/*") for p in prefix.splitlines()):
                code = code[pkg_idx:]

        # Parse basic imports (Python, Go, Rust, JS)
        imports = []
        for line in code.splitlines():
            line_str = line.strip()
            if (
                line_str.startswith("import ")
                or line_str.startswith("from ")
                or line_str.startswith("use ")
                or line_str.startswith("#include")
            ):
                imports.append(line_str)

        return ChunkOutput(subgoal_id=subgoal_id, code=code, imports=imports)


    def _mock_synthesize(self, subgoal: SubGoal) -> ChunkOutput:
        """Deterministic reference implementations for mock testing."""
        if subgoal.id == "node_store":
            code = (
                "class MemoryStore:\n"
                "    def __init__(self):\n"
                "        self._data = {}\n\n"
                "    def set(self, key: str, value: str) -> None:\n"
                "        self._data[key] = value\n\n"
                "    def get(self, key: str) -> str | None:\n"
                "        return self._data.get(key, None)\n"
            )
            return ChunkOutput(subgoal_id=subgoal.id, code=code)

        if subgoal.id == "node_cache":
            code = (
                "from collections import OrderedDict\n\n"
                "class LRUCache:\n"
                "    def __init__(self, capacity: int = 10):\n"
                "        self.capacity = capacity\n"
                "        self._cache = OrderedDict()\n\n"
                "    def put(self, key: str, value: str) -> None:\n"
                "        if key in self._cache:\n"
                "            self._cache.move_to_end(key)\n"
                "        self._cache[key] = value\n"
                "        if len(self._cache) > self.capacity:\n"
                "            self._cache.popitem(last=False)\n\n"
                "    def get(self, key: str) -> str | None:\n"
                "        if key not in self._cache:\n"
                "            return None\n"
                "        self._cache.move_to_end(key)\n"
                "        return self._cache[key]\n"
            )
            return ChunkOutput(
                subgoal_id=subgoal.id,
                code=code,
                imports=["from collections import OrderedDict"],
            )

        # Fallback dummy implementation for any generated node
        if subgoal.module_path.endswith(".go"):
            lines = ["package main\n"]
            for contract in subgoal.public_contracts:
                if contract.symbol_type in ("struct", "type", "class"):
                    lines.append(f"type {contract.symbol_name} struct {{}}\n")
                else:
                    lines.append(f"func {contract.symbol_name}() {{}}\n")
            lines.append("func main() {}\n")
            return ChunkOutput(subgoal_id=subgoal.id, code="\n".join(lines))

        lines = []
        for contract in subgoal.public_contracts:
            if contract.symbol_type in ("class", "struct"):
                lines.append(f"class {contract.symbol_name}:\n    pass\n")
            elif contract.symbol_type in ("function", "async_function", "method"):
                is_async = "async " if contract.symbol_type == "async_function" else ""
                lines.append(f"{is_async}def {contract.symbol_name}():\n    return None\n")
        return ChunkOutput(subgoal_id=subgoal.id, code="\n".join(lines))

