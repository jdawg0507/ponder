"""Discrete Verification Gate for H-JEPA Coding Agent."""

from __future__ import annotations
import ast
import os
import re
import subprocess
import sys
import tempfile
import threading
from typing import Any, List, Optional
from ponder.models import ChunkOutput, SubGoal, SymbolContract, VerificationResult


class VerificationGate:
    """Deterministic verification gate validating syntax, contracts, and invariants."""

    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()

    def verify(
        self,
        subgoal: SubGoal,
        chunk: ChunkOutput,
        upstream_contracts: Optional[List[SymbolContract]] = None,
        hard_givens: Optional[Any] = None,
        workspace_dir: Optional[str] = None,
        is_final_subgoal: bool = True,
    ) -> VerificationResult:
        """Run all verification stages sequentially across any supported language."""
        # Fast pre-check: empty code rejection (0ms)
        if not chunk.code or not chunk.code.strip():
            return VerificationResult(
                passed=False,
                stage="syntax",
                error_message="Code chunk is empty.",
            )

        target_lang = getattr(hard_givens, "target_language", "python") if hard_givens else "python"

        # 1. Custom Verification Command (e.g. CodeCrafters runner or custom test script)
        if subgoal.verification_spec.custom_verify_cmd:
            with self._lock:
                cmd_res = self.run_toolchain_command(
                    cmd=subgoal.verification_spec.custom_verify_cmd,
                    cwd=workspace_dir,
                    target_lang=target_lang,
                )
                if not cmd_res.passed:
                    return cmd_res

        # 2. Native Compiler / Syntax Verification for compiled languages (Go, Rust, C)
        if target_lang != "python" and workspace_dir:
            from pathlib import Path
            target_file = Path(workspace_dir) / subgoal.module_path
            with self._lock:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                prev_content = target_file.read_text(encoding="utf-8") if target_file.exists() else None

            try:
                # Stage candidate code
                target_file.write_text(chunk.code, encoding="utf-8")

                if hard_givens and hard_givens.toolchain.compile_cmd:
                    compile_cmd = hard_givens.toolchain.compile_cmd
                    comp_res = self.run_toolchain_command(
                        cmd=compile_cmd,
                        cwd=workspace_dir,
                        target_lang=target_lang,
                    )
                    # Auto-heal Go unused imports if compiler failed due to 'imported and not used'
                    if not comp_res.passed and "imported and not used" in (comp_res.error_message or ""):
                        import re
                        unused_pkgs = re.findall(r'"([^"]+)" imported and not used', comp_res.error_message or "")
                        if unused_pkgs:
                            new_lines = []
                            for line in chunk.code.splitlines():
                                if any(f'"{pkg}"' in line or f"'{pkg}'" in line for pkg in unused_pkgs):
                                    continue
                                new_lines.append(line)
                            chunk.code = "\n".join(new_lines)
                            target_file.write_text(chunk.code, encoding="utf-8")
                            comp_res = self.run_toolchain_command(
                                cmd=compile_cmd,
                                cwd=workspace_dir,
                                target_lang=target_lang,
                            )

                    if not comp_res.passed and "function main is undeclared in the main package" in (comp_res.error_message or ""):
                        vet_res = self.run_toolchain_command("go vet ./...", cwd=workspace_dir, target_lang=target_lang)
                        if vet_res.passed:
                            comp_res = vet_res

                    if not comp_res.passed:
                        # Revert on compiler failure
                        if prev_content is not None:
                            target_file.write_text(prev_content, encoding="utf-8")
                        else:
                            target_file.unlink(missing_ok=True)
                        return comp_res

                if is_final_subgoal and hard_givens and hard_givens.toolchain.test_cmd:
                    test_res = self.run_toolchain_command(
                        cmd=hard_givens.toolchain.test_cmd,
                        cwd=workspace_dir,
                        target_lang=target_lang,
                    )
                    if not test_res.passed:
                        # Ignore "no test files" / "no packages to test" if compilation passed
                        err_str = test_res.error_message or ""
                        if any(k in err_str for k in ("no test files", "no packages to test", "[no test files]", "collected 0 items", "no tests ran")):
                            pass
                        else:
                            if prev_content is not None:
                                target_file.write_text(prev_content, encoding="utf-8")
                            else:
                                target_file.unlink(missing_ok=True)
                            return test_res
            except Exception as e:
                return VerificationResult(passed=False, stage="test_harness", error_message=str(e))

        elif target_lang == "python":
            syntax_res = self.check_syntax(chunk.code)
            if not syntax_res.passed:
                return syntax_res

            # 3. Signature Concordance Check for Python
            sig_res = self.check_signatures(chunk.code, subgoal.public_contracts)
            if not sig_res.passed:
                return sig_res

            # 4. Invariant Test Harness for Python
            if subgoal.verification_spec.test_harness_code:
                test_res = self.run_test_harness(
                    code=chunk.code,
                    test_code=subgoal.verification_spec.test_harness_code,
                    module_path=subgoal.module_path,
                )
                if not test_res.passed:
                    return test_res

            if workspace_dir:
                from pathlib import Path
                target_file = Path(workspace_dir) / subgoal.module_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(chunk.code, encoding="utf-8")

        return VerificationResult(passed=True)


    def run_toolchain_command(
        self,
        cmd: str,
        cwd: Optional[str] = None,
        target_lang: Optional[str] = None,
    ) -> VerificationResult:
        """Executes a native toolchain command, seamlessly routed to Docker container if host toolchain is absent."""
        import shutil
        from pathlib import Path

        actual_cmd = cmd
        actual_cwd = cwd
        env = os.environ.copy()

        # Check if binary exists on host
        first_token = cmd.split()[0] if cmd.split() else ""
        if target_lang == "python" or cmd.startswith("pytest") or cmd.startswith("python"):
            if cmd.startswith("pytest"):
                actual_cmd = f"{sys.executable} -m {cmd}"
            elif cmd.startswith("python "):
                actual_cmd = f"{sys.executable} " + cmd[len("python "):]
            use_docker_container = False
        else:
            host_has_compiler = bool(shutil.which(first_token))
            use_docker_container = (not host_has_compiler) and bool(shutil.which("docker"))

        if use_docker_container and cwd:
            abs_cwd = str(Path(cwd).resolve())
            img_map = {
                "rust": "rust:slim",
                "go": "golang:alpine",
                "cpp": "gcc:latest",
                "c": "gcc:latest",
                "java": "openjdk:17-slim",
            }
            container_img = img_map.get(target_lang or "", "ubuntu:latest")
            actual_cmd = f'docker run --rm -v "{abs_cwd}:/app" -w /app {container_img} /bin/sh -c "{cmd}"'
            actual_cwd = None
        else:
            if cwd:
                cache_dir = Path(cwd).resolve() / ".cache"
                (cache_dir / "go").mkdir(parents=True, exist_ok=True)
                (cache_dir / "cargo").mkdir(parents=True, exist_ok=True)
                (cache_dir / "ccache").mkdir(parents=True, exist_ok=True)
                env.setdefault("GOCACHE", str((cache_dir / "go").resolve()))
                env.setdefault("CARGO_TARGET_DIR", str((cache_dir / "cargo").resolve()))
                env.setdefault("CCACHE_DIR", str((cache_dir / "ccache").resolve()))

        try:
            proc = subprocess.run(
                actual_cmd,
                shell=True,
                cwd=actual_cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if proc.returncode == 0:
                return VerificationResult(passed=True)

            error_output = proc.stderr.strip() or proc.stdout.strip()
            return VerificationResult(
                passed=False,
                stage="test_harness",
                error_message=f"Command '{cmd}' failed (exit code {proc.returncode}):\n{error_output}",
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                passed=False,
                stage="test_harness",
                error_message=f"Command '{cmd}' timed out after {self.timeout_seconds}s.",
            )
        except Exception as e:
            return VerificationResult(
                passed=False,
                stage="test_harness",
                error_message=f"Execution error running '{cmd}': {str(e)}",
            )


    def check_syntax(self, code: str) -> VerificationResult:
        """Parses the code into a Python AST."""
        try:
            ast.parse(code)
            return VerificationResult(passed=True, stage="syntax")
        except SyntaxError as e:
            err = f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}\nCode snippet:\n{e.text}"
            return VerificationResult(
                passed=False,
                stage="syntax",
                error_message=err,
            )

    def check_signatures(
        self,
        code: str,
        expected_contracts: List[SymbolContract],
    ) -> VerificationResult:
        """Ensures all public contracts declared in Level 2 exist with matching signatures."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return VerificationResult(passed=False, stage="syntax", error_message=str(e))

        defined_funcs = {}
        defined_classes = {}

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [arg.arg for arg in node.args.args]
                defined_funcs[node.name] = {
                    "node": node,
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "args": args,
                }
            elif isinstance(node, ast.ClassDef):
                defined_classes[node.name] = node

        for contract in expected_contracts:
            name = contract.symbol_name

            if contract.symbol_type == "class":
                if name not in defined_classes:
                    return VerificationResult(
                        passed=False,
                        stage="signature",
                        error_message=f"Missing expected class definition '{name}'.",
                    )
            elif contract.symbol_type in ("function", "async_function"):
                if name not in defined_funcs:
                    return VerificationResult(
                        passed=False,
                        stage="signature",
                        error_message=f"Missing expected function definition '{name}'.",
                    )
                func_info = defined_funcs[name]
                if contract.symbol_type == "async_function" and not func_info["is_async"]:
                    return VerificationResult(
                        passed=False,
                        stage="signature",
                        error_message=f"Function '{name}' was expected to be async but is synchronous.",
                    )
                if contract.symbol_type == "function" and func_info["is_async"]:
                    return VerificationResult(
                        passed=False,
                        stage="signature",
                        error_message=f"Function '{name}' was expected to be synchronous but is async.",
                    )

                # Check parameter names from contract signature
                param_match = re.search(r"\((.*?)\)", contract.signature)
                if param_match:
                    params_raw = param_match.group(1).strip()
                    if params_raw:
                        # Extract parameter names ignoring types/defaults
                        expected_params = []
                        for part in params_raw.split(","):
                            clean_part = part.split(":")[0].split("=")[0].strip()
                            if clean_part and clean_part != "*":
                                expected_params.append(clean_part)

                        actual_params = func_info["args"]
                        if expected_params != actual_params:
                            return VerificationResult(
                                passed=False,
                                stage="signature",
                                error_message=(
                                    f"Signature parameter mismatch for '{name}'. "
                                    f"Expected {expected_params}, got {actual_params}."
                                ),
                            )

        return VerificationResult(passed=True, stage="signature")

    def run_test_harness(
        self,
        code: str,
        test_code: str,
        module_path: Optional[str] = None,
    ) -> VerificationResult:
        """Executes the test harness against the candidate chunk in an isolated subprocess."""
        if not test_code.strip():
            return VerificationResult(passed=True, stage="test_harness")

        from pathlib import Path
        mod_stem = Path(module_path).stem if module_path else ""

        runner_script = f"""
import sys
import types

# Candidate Code
{code}

# Register candidate module in sys.modules for in-memory resolution
_mod_name = "{mod_stem}"
if _mod_name:
    _m = types.ModuleType(_mod_name)
    for _k, _v in list(locals().items()):
        if not _k.startswith('__'):
            setattr(_m, _k, _v)
    sys.modules[_mod_name] = _m

# Test Harness
{test_code}

if __name__ == '__main__':
    # Discover and run any test_ functions defined in test_code
    local_symbols = list(locals().items())
    for name, obj in local_symbols:
        if callable(obj) and name.startswith('test_'):
            obj()
    print("__PONDER_VERIFICATION_SUCCESS__")
"""

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=True) as tmp:
            tmp.write(runner_script)
            tmp.flush()

            try:
                proc = subprocess.run(
                    [sys.executable, tmp.name],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
                if proc.returncode == 0 and (
                    "__PONDER_VERIFICATION_SUCCESS__" in proc.stdout
                    or "__HJEPA_VERIFICATION_SUCCESS__" in proc.stdout
                ):
                    return VerificationResult(passed=True, stage="test_harness")

                error_msg = proc.stderr.strip() or proc.stdout.strip()
                return VerificationResult(
                    passed=False,
                    stage="test_harness",
                    error_message=f"Test harness failed:\n{error_msg}",
                )
            except subprocess.TimeoutExpired:
                return VerificationResult(
                    passed=False,
                    stage="test_harness",
                    error_message=f"Test harness timed out after {self.timeout_seconds}s.",
                )
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    stage="test_harness",
                    error_message=f"Test harness error: {str(e)}",
                )
