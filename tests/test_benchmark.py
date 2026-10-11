"""Unit tests for CCBench Evaluation Runner."""

from ponder.benchmarks.ccbench import (
    CURATED_CCBENCH_TASKS,
    CCBenchRunner,
    CCBenchTask,
)
from ponder.client import NebiusClient


def test_ccbench_task_execution(tmp_path):
    client = NebiusClient(mock_mode=True)
    runner = CCBenchRunner(base_workspace=str(tmp_path), client=client)

    task = CCBenchTask(
        id="test-task",
        title="Test Task",
        track="test",
        language="python",
        instructions="Build an LRU cache",
    )

    result = runner.run_task(task)
    assert result.task_id == "test-task"
    assert result.passed is True
    assert result.duration_seconds >= 0.0
    assert result.tokens_used > 0
    assert result.cost_usd > 0.0


def test_ccbench_suite_summary(tmp_path):
    events = []
    client = NebiusClient(mock_mode=True)
    runner = CCBenchRunner(
        base_workspace=str(tmp_path),
        client=client,
        on_event=lambda ev, data: events.append(ev),
    )

    summary = runner.run_suite(CURATED_CCBENCH_TASKS[:2])
    assert summary["total_tasks"] == 2
    assert summary["passed_tasks"] == 2
    assert summary["pass_rate_percent"] == 100.0
    assert "suite_complete" in events
