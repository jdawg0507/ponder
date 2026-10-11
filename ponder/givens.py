"""Level 3 Invariant Anchor: Extracts and freezes immutable problem givens."""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional
from ponder.client import LEVEL_1_DEFAULT_MODEL, NebiusClient
from ponder.models import HardGivens, ToolchainConfig


HARD_GIVENS_SYSTEM_PROMPT = """You are the Level 3 Invariant Anchor in the Ponder Coding Agent architecture.
Your sole job is to establish the frozen "Hard Givens" of the engineering problem before any planning occurs.

You must emit a valid JSON object matching the HardGivens schema:
{
  "target_language": "python | rust | go | typescript | c | generic",
  "toolchain": {
    "compile_cmd": "e.g. cargo check, go build -o /dev/null ./..., python -m py_compile",
    "test_cmd": "e.g. cargo test, go test ./..., pytest",
    "lint_cmd": "e.g. cargo clippy, go vet, ruff check"
  },
  "protocols_and_specs": ["List of non-negotiable protocol rules, wire formats, algorithms"],
  "allowed_dependencies": ["Allowed external packages/libraries or standard library only"],
  "boundary_constraints": ["Files or components that must not be modified or boundaries to respect"],
  "acceptance_criteria": ["Explicit, unambiguous criteria required for task completion"]
}

Do NOT write code or design DAG nodes. Only establish the immutable givens and toolchain constraints.
"""


class HardGivensExtractor:
    """Pass 0 extractor freezing problem boundaries and toolchain contracts."""

    def __init__(self, client: NebiusClient, model: str = LEVEL_1_DEFAULT_MODEL):
        self.client = client
        self.model = model

    def extract(self, requirement: str, workspace_dir: Optional[str] = None) -> HardGivens:
        """Extracts hard givens, detecting existing repository toolchains if present."""
        detected_context, detected_lang, default_toolchain = self._detect_repo_context(workspace_dir, requirement)

        if self.client.mock_mode:
            return self._mock_givens(requirement, detected_lang)

        user_content = f"Requirement:\n{requirement[:1200]}\n"
        if detected_context:
            user_content += f"\nExisting Workspace Context:\n{detected_context}\n"

        messages = [
            {"role": "system", "content": HARD_GIVENS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            raw_json = self.client.complete_structured(
                model=self.model,
                messages=messages,
            )
            data = json.loads(raw_json)
            givens = HardGivens.model_validate(data)
        except Exception:
            givens = HardGivens()

        # Anchor language and toolchains if missing or mismatched with detected environment
        if detected_lang and (givens.target_language == "python" and detected_lang != "python"):
            givens.target_language = detected_lang
        elif not givens.target_language:
            givens.target_language = detected_lang or "python"

        if default_toolchain:
            if default_toolchain.compile_cmd:
                givens.toolchain.compile_cmd = default_toolchain.compile_cmd
            if default_toolchain.test_cmd:
                givens.toolchain.test_cmd = default_toolchain.test_cmd

        if givens.toolchain.compile_cmd:
            givens.toolchain.compile_cmd = givens.toolchain.compile_cmd.replace("-Werror", "").strip()

        if workspace_dir and Path(workspace_dir).exists():
            path = Path(workspace_dir)
            existing_srcs = []
            for ext in ("*.go", "*.rs", "*.py", "*.cpp", "*.c", "*.ts", "*.js"):
                for f in path.rglob(ext):
                    if not any(part.startswith(".") for part in f.parts):
                        existing_srcs.append(str(f.relative_to(path)))
            givens.existing_files = existing_srcs[:15]

        return givens

    def _detect_repo_context(self, workspace_dir: Optional[str], requirement: str = "") -> tuple[str, str, Optional[ToolchainConfig]]:
        """Detects language and manifest files in the target workspace."""
        path = Path(workspace_dir) if workspace_dir else None
        context_items = []
        detected_lang = ""
        toolchain = None

        req_lower = requirement.lower()

        if path and path.exists():
            # 1. Check CodeCrafters configuration if present
            cc_yml = path / "codecrafters.yml"
            if cc_yml.exists():
                try:
                    yml_content = cc_yml.read_text(encoding="utf-8").lower()
                    if "cpp" in yml_content or "c++" in yml_content:
                        detected_lang = "cpp"
                    elif "rust" in yml_content:
                        detected_lang = "rust"
                    elif "go" in yml_content:
                        detected_lang = "go"
                    elif "java" in yml_content:
                        detected_lang = "java"
                    elif "python" in yml_content:
                        detected_lang = "python"
                except Exception:
                    pass

            # 2. Check native manifests and source extensions
            if not detected_lang:
                if (path / "CMakeLists.txt").exists() or list(path.rglob("*.cpp")) or list(path.rglob("*.hpp")):
                    detected_lang = "cpp"
                    context_items.append("C++ project detected (CMakeLists.txt / *.cpp present).")
                elif (path / "Cargo.toml").exists() or list(path.rglob("*.rs")):
                    detected_lang = "rust"
                    context_items.append("Rust project detected (Cargo.toml present).")
                elif (path / "go.mod").exists() or list(path.rglob("*.go")):
                    detected_lang = "go"
                    context_items.append("Go project detected (go.mod present).")
                elif (path / "pom.xml").exists() or list(path.rglob("*.java")):
                    detected_lang = "java"
                    context_items.append("Java project detected.")
                elif (path / "pyproject.toml").exists() or (path / "setup.py").exists() or list(path.rglob("*.py")):
                    detected_lang = "python"
                    context_items.append("Python project detected.")

            # 3. Detect compiler command
            compile_sh = path / ".codecrafters" / "compile.sh"
            if detected_lang == "cpp":
                toolchain = ToolchainConfig(compile_cmd="clang++ -std=c++20 -fsyntax-only src/*.cpp")
            elif compile_sh.exists():
                toolchain = ToolchainConfig(compile_cmd="sh .codecrafters/compile.sh")
            elif detected_lang == "rust":
                toolchain = ToolchainConfig(compile_cmd="cargo check", test_cmd="cargo test")
            elif detected_lang == "go":
                go_target = "./app/main.go" if (path / "app" / "main.go").exists() else "./..."
                toolchain = ToolchainConfig(compile_cmd=f"go build {go_target}", test_cmd="go test ./...")
            elif detected_lang == "java":
                toolchain = ToolchainConfig(compile_cmd="javac src/main/java/**/*.java")
            elif detected_lang == "python":
                toolchain = ToolchainConfig(compile_cmd="python3 -m py_compile", test_cmd="pytest -v")

        # 4. Fallback to requirement text markers
        if not detected_lang:
            if " - cpp" in req_lower or "[grep - cpp]" in req_lower or "language: cpp" in req_lower or "(cpp)" in req_lower or " c++" in req_lower:
                detected_lang = "cpp"
                toolchain = ToolchainConfig(compile_cmd="clang++ -std=c++20 -fsyntax-only src/*.cpp")
            elif " - go" in req_lower or "[grep - go]" in req_lower or "language: go" in req_lower or "(go)" in req_lower:
                detected_lang = "go"
                toolchain = ToolchainConfig(compile_cmd="go build ./app/main.go" if path and (path / "app" / "main.go").exists() else "go build ./...", test_cmd="go test ./...")
            elif " - rust" in req_lower or "language: rust" in req_lower or "(rust)" in req_lower:
                detected_lang = "rust"
                toolchain = ToolchainConfig(compile_cmd="cargo check", test_cmd="cargo test")
            elif " - java" in req_lower or "language: java" in req_lower or "(java)" in req_lower:
                detected_lang = "java"
                toolchain = ToolchainConfig(compile_cmd="javac src/main/java/**/*.java")
            elif " - python" in req_lower or "language: python" in req_lower or "(python)" in req_lower:
                detected_lang = "python"
                toolchain = ToolchainConfig(compile_cmd="python3 -m py_compile", test_cmd="pytest -v")

        if path and path.exists():
            existing_srcs = []
            for ext in ("*.go", "*.rs", "*.py", "*.cpp", "*.c", "*.ts", "*.js", "*.java"):
                for f in path.rglob(ext):
                    if not any(part.startswith(".") for part in f.parts):
                        existing_srcs.append(str(f.relative_to(path)))
            if existing_srcs:
                context_items.append(f"Existing source files to edit: {', '.join(existing_srcs[:10])}")

        return " ".join(context_items), detected_lang, toolchain

    def _mock_givens(self, requirement: str, detected_lang: str = "") -> HardGivens:
        """Deterministic hard givens for mock testing."""
        req_lower = requirement.lower()
        if detected_lang == "cpp" or "cpp" in req_lower or "c++" in req_lower:
            return HardGivens(
                target_language="cpp",
                toolchain=ToolchainConfig(
                    compile_cmd="cmake -B build -S . && cmake --build ./build",
                    test_cmd="",
                    lint_cmd="",
                ),
                protocols_and_specs=["C++20 / C++23 stdlib"],
                allowed_dependencies=["Standard library only"],
                acceptance_criteria=["Zero compile errors with cmake"],
            )

        if detected_lang == "rust" or "rust" in req_lower:
            return HardGivens(
                target_language="rust",
                toolchain=ToolchainConfig(
                    compile_cmd="cargo check",
                    test_cmd="cargo test",
                    lint_cmd="cargo clippy",
                ),
                protocols_and_specs=["Rust 2021 Edition"],
                allowed_dependencies=["Standard library only"],
                acceptance_criteria=["Clean compilation with 0 warnings"],
            )

        if detected_lang == "go" or "go" in req_lower:
            return HardGivens(
                target_language="go",
                toolchain=ToolchainConfig(
                    compile_cmd="go build -o /dev/null ./...",
                    test_cmd="go test ./...",
                    lint_cmd="go vet",
                ),
                protocols_and_specs=["Go 1.21+"],
                allowed_dependencies=["Standard library only"],
                acceptance_criteria=["Zero compile errors and all go tests pass"],
            )

        return HardGivens(
            target_language="python",
            toolchain=ToolchainConfig(
                compile_cmd="python -m py_compile",
                test_cmd="pytest -v",
                lint_cmd="ruff check",
            ),
            protocols_and_specs=["Python 3.11+ strict typing"],
            allowed_dependencies=["Standard library only"],
            acceptance_criteria=["Syntax valid and invariant assertions pass"],
        )
