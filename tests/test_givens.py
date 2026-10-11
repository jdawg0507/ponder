"""Unit tests for the Level 3 Hard Givens Extractor."""

from ponder.client import NebiusClient
from ponder.givens import HardGivensExtractor


def test_givens_extraction_python():
    client = NebiusClient(mock_mode=True)
    extractor = HardGivensExtractor(client)
    givens = extractor.extract("Build a python math library")

    assert givens.target_language == "python"
    assert "py_compile" in (givens.toolchain.compile_cmd or "")


def test_givens_extraction_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'test'\nversion = '0.1.0'\n")

    client = NebiusClient(mock_mode=True)
    extractor = HardGivensExtractor(client)
    givens = extractor.extract("Implement a queue", workspace_dir=str(tmp_path))

    assert givens.target_language == "rust"
    assert givens.toolchain.compile_cmd == "cargo check"
    assert givens.toolchain.test_cmd == "cargo test"


def test_givens_extraction_go(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/test\n\ngo 1.21\n")

    client = NebiusClient(mock_mode=True)
    extractor = HardGivensExtractor(client)
    givens = extractor.extract("Implement key-value store", workspace_dir=str(tmp_path))

    assert givens.target_language == "go"
    assert "go build" in (givens.toolchain.compile_cmd or "")
    assert "go test" in (givens.toolchain.test_cmd or "")
