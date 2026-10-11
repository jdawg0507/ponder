"""Unit tests for the Discrete Verification Gate."""

from ponder.models import ChunkOutput, SubGoal, SymbolContract, VerificationSpec
from ponder.verifier import VerificationGate


def test_syntax_checker_valid():
    gate = VerificationGate()
    res = gate.check_syntax("def add(a: int, b: int) -> int:\n    return a + b\n")
    assert res.passed is True


def test_syntax_checker_invalid():
    gate = VerificationGate()
    res = gate.check_syntax("def broken(\n    return 42\n")
    assert res.passed is False
    assert res.stage == "syntax"
    assert "SyntaxError" in res.error_message


def test_signature_concordance_success():
    gate = VerificationGate()
    contracts = [
        SymbolContract(
            symbol_name="compute_metrics",
            symbol_type="function",
            signature="def compute_metrics(data: list, scale: float) -> dict:",
        )
    ]
    code = "def compute_metrics(data, scale):\n    return {}\n"
    res = gate.check_signatures(code, contracts)
    assert res.passed is True


def test_signature_concordance_missing_symbol():
    gate = VerificationGate()
    contracts = [
        SymbolContract(
            symbol_name="compute_metrics",
            symbol_type="function",
            signature="def compute_metrics(data: list) -> dict:",
        )
    ]
    code = "def other_func():\n    pass\n"
    res = gate.check_signatures(code, contracts)
    assert res.passed is False
    assert "Missing expected function definition" in res.error_message


def test_signature_concordance_arg_mismatch():
    gate = VerificationGate()
    contracts = [
        SymbolContract(
            symbol_name="fetch_user",
            symbol_type="function",
            signature="def fetch_user(user_id: str, timeout: int) -> dict:",
        )
    ]
    code = "def fetch_user(id, timeout):\n    return {}\n"
    res = gate.check_signatures(code, contracts)
    assert res.passed is False
    assert "Signature parameter mismatch" in res.error_message


def test_test_harness_pass():
    gate = VerificationGate()
    code = "def double(x: int) -> int:\n    return x * 2\n"
    test_code = "def test_double():\n    assert double(3) == 6\n"
    res = gate.run_test_harness(code, test_code)
    assert res.passed is True


def test_test_harness_fail():
    gate = VerificationGate()
    code = "def double(x: int) -> int:\n    return x * 3\n"
    test_code = "def test_double():\n    assert double(3) == 6\n"
    res = gate.run_test_harness(code, test_code)
    assert res.passed is False
    assert "AssertionError" in res.error_message


def test_toolchain_command_success():
    gate = VerificationGate()
    res = gate.run_toolchain_command("python3 -c 'exit(0)'")
    assert res.passed is True


def test_toolchain_command_failure():
    gate = VerificationGate()
    res = gate.run_toolchain_command("python3 -c 'import sys; sys.stderr.write(\"Compile error\"); exit(1)'")
    assert res.passed is False
    assert "Compile error" in res.error_message

