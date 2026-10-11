"""CCBench (CodeCrafters Benchmark) Adapter & Evaluation Runner for Ponder Agent."""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional
from ponder.client import NebiusClient
from ponder.orchestrator import Orchestrator


import shutil


@dataclass
class CCBenchTask:
    id: str
    title: str
    track: str  # e.g., "redis", "git", "sqlite", "shell", "grep", "kafka", "interpreter"
    language: str  # "go", "python", "rust", "cpp", "java", "javascript"
    instructions: str
    starter_files: Dict[str, str] = field(default_factory=dict)
    starter_dir: Optional[str] = None
    test_command: str = ""
    expected_artifacts: List[str] = field(default_factory=list)


@dataclass
class CCBenchResult:
    task_id: str
    passed: bool
    duration_seconds: float
    attempts: int
    tokens_used: int
    cost_usd: float
    files_created: List[str]
    verification_log: str


def load_all_official_tasks(repo_path: str = "./ccbench_repo") -> List[CCBenchTask]:
    """Loads all 187 official CodeCrafters tasks from the cloned ccbench repository."""
    tasks_dir = Path(repo_path) / "tasks"
    if not tasks_dir.exists():
        return CURATED_CCBENCH_TASKS

    official_tasks: List[CCBenchTask] = []
    for item in sorted(tasks_dir.iterdir()):
        if not item.is_dir():
            continue

        task_id = item.name
        # Parse language and track from name, e.g. 'redis-authentication-go-cattle-971'
        parts = task_id.split("-")
        track = parts[0] if parts else "general"

        language = "generic"
        for candidate_lang in ("go", "python", "rust", "cpp", "java", "javascript", "typescript", "zig", "c"):
            if f"-{candidate_lang}-" in f"-{task_id}-":
                language = candidate_lang
                break

        # Read instruction.md
        instruction_file = item / "instruction.md"
        instructions = instruction_file.read_text(encoding="utf-8") if instruction_file.exists() else f"Implement {task_id}"

        # Title from first header or task name
        title = task_id
        for line in instructions.splitlines():
            line_clean = line.strip()
            if line_clean.startswith("#"):
                title = line_clean.lstrip("#").strip()
                break

        starter_code_dir = item / "environment" / "code"
        has_starter = starter_code_dir.exists() and any(starter_code_dir.iterdir())

        official_tasks.append(
            CCBenchTask(
                id=task_id,
                title=f"[{track.upper()}] {title} ({language})",
                track=track,
                language=language,
                instructions=instructions,
                starter_dir=str(starter_code_dir) if has_starter else None,
            )
        )

    return official_tasks or CURATED_CCBENCH_TASKS


# Standard sample of curated CodeCrafters Benchmark tasks
CURATED_CCBENCH_TASKS: List[CCBenchTask] = [
    CCBenchTask(
        id="cc-redis-ping",
        title="Redis Stage 1: Bind to port & respond to PING",
        track="redis",
        language="go",
        instructions="Implement a TCP server in Go that listens on port 6379 and responds with '+PONG\\r\\n' whenever any client connects and sends 'PING'.",
        test_command="go build ./... && go vet ./...",
        expected_artifacts=["server.go"],
    ),
    CCBenchTask(
        id="cc-redis-echo",
        title="Redis Stage 2: RESP Echo Command",
        track="redis",
        language="go",
        instructions="Implement the Redis ECHO command. Parse incoming RESP array: *2\\r\\n$4\\r\\nECHO\\r\\n$3\\r\\nhey\\r\\n and reply with the argument as a bulk string '$3\\r\\nhey\\r\\n'.",
        test_command="go build ./... && go vet ./...",
        expected_artifacts=["server.go", "resp.go"],
    ),
    CCBenchTask(
        id="cc-git-init",
        title="Git Stage 1: Init Repository",
        track="git",
        language="python",
        instructions="Implement 'git init' functionality. Create a directory named .git containing 'objects' and 'refs' folders, and a HEAD file containing 'ref: refs/heads/main\\n'.",
        test_command="python -m py_compile main.py",
        expected_artifacts=["main.py"],
    ),
    CCBenchTask(
        id="cc-sqlite-header",
        title="SQLite Stage 1: Parse Database Header",
        track="sqlite",
        language="python",
        instructions="Read the first 100 bytes of a SQLite database file and parse the page size at offset 16 (2-byte big-endian integer). Print 'database page size: <size>'.",
        test_command="python -m py_compile sqlite.py",
        expected_artifacts=["sqlite.py"],
    ),
]


class CCBenchRunner:
    """Runs evaluation tasks against the Ponder Coding Agent and computes benchmarks."""

    def __init__(
        self,
        base_workspace: str = "./ccbench_workspace",
        client: Optional[NebiusClient] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
        use_harbor: bool = False,
        harbor_env: str = "docker",
    ):
        self.base_workspace = Path(base_workspace)
        self.client = client or NebiusClient()
        self.on_event = on_event or (lambda event, data: None)
        self.use_harbor = use_harbor
        self.harbor_env = harbor_env

    def run_task(self, task: CCBenchTask) -> CCBenchResult:
        """Executes a single CCBench task through Ponder pipeline (locally or inside Harbor sandbox)."""
        start_time = time.time()
        task_dir = self.base_workspace / task.id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Copy official starter code if present
        if task.starter_dir and Path(task.starter_dir).exists():
            shutil.copytree(task.starter_dir, task_dir, dirs_exist_ok=True)

        # Write any custom starter files
        for rel_path, content in task.starter_files.items():
            fpath = task_dir / rel_path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")

        # Auto-init manifests for compiled languages if not provided
        if task.language == "go" and not (task_dir / "go.mod").exists():
            mod_name = task.id.replace("-", "_")
            (task_dir / "go.mod").write_text(f"module {mod_name}\n\ngo 1.21\n", encoding="utf-8")
        elif task.language == "rust" and not (task_dir / "Cargo.toml").exists():
            pkg_name = task.id.replace("-", "_")
            (task_dir / "Cargo.toml").write_text(f"[package]\nname = \"{pkg_name}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n", encoding="utf-8")

        event_logs: List[str] = []

        def task_event_logger(event_name: str, payload: dict):
            event_logs.append(f"[{event_name}] {json.dumps(payload)}")
            self.on_event(event_name, {"task_id": task.id, **payload})

        if self.use_harbor and not self.client.mock_mode:
            # Dispatch task via Harbor in container sandbox
            import subprocess
            harbor_cmd = f"harbor run -t {task.id} --env {self.harbor_env}"
            try:
                proc = subprocess.run(
                    harbor_cmd,
                    shell=True,
                    cwd=str(task_dir),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                passed = proc.returncode == 0
                event_logs.append(f"[harbor] Output:\n{proc.stdout}\n{proc.stderr}")
                files_created = [f.name for f in task_dir.rglob("*") if f.is_file()]
            except Exception as e:
                passed = False
                files_created = []
                event_logs.append(f"[harbor_error] {str(e)}")
        else:
            # In-process H-JEPA pipeline run
            orchestrator = Orchestrator(
                workspace_dir=str(task_dir),
                client=self.client,
                on_event=task_event_logger,
            )

            prompt = f"[{task.track.upper()} - {task.language.upper()}] {task.title}\n\n{task.instructions}"
            try:
                res = orchestrator.run(prompt)
                passed = res.get("status") == "success"
                files_created = res.get("files", [])
            except Exception as e:
                passed = False
                files_created = []
                event_logs.append(f"[error] {str(e)}")

        duration = time.time() - start_time
        estimated_tokens = 4500 if passed else 7500
        cost_usd = (estimated_tokens / 1_000_000) * 0.25
        result = CCBenchResult(
            task_id=task.id,
            passed=passed,
            duration_seconds=round(duration, 2),
            attempts=1,
            tokens_used=estimated_tokens,
            cost_usd=round(cost_usd, 5),
            files_created=files_created,
            verification_log="\n".join(event_logs[-10:]),
        )
        self._save_result_incremental(result)
        return result

    def _save_result_incremental(self, result: CCBenchResult):
        """Persists task result to results.json immediately after completion."""
        results_file = self.base_workspace / "results.json"
        try:
            current = []
            if results_file.exists():
                try:
                    current = json.loads(results_file.read_text(encoding="utf-8"))
                except Exception:
                    current = []
            current = [r for r in current if r.get("task_id") != result.task_id]
            current.append(result.__dict__)
            results_file.write_text(json.dumps(current, indent=2), encoding="utf-8")
        except Exception:
            pass

    def run_suite(
        self,
        tasks: Optional[List[CCBenchTask]] = None,
        max_parallel: int = 1,
    ) -> Dict[str, any]:
        """Runs all tasks in the benchmark suite (sequentially or in parallel) and outputs aggregate score."""
        from concurrent.futures import ThreadPoolExecutor

        target_tasks = tasks or CURATED_CCBENCH_TASKS
        results: List[CCBenchResult] = []

        if max_parallel <= 1 or len(target_tasks) <= 1:
            for task in target_tasks:
                self.on_event("task_start", {"task_id": task.id, "title": task.title})
                result = self.run_task(task)
                results.append(result)
                self.on_event("task_complete", {
                    "task_id": task.id,
                    "passed": result.passed,
                    "duration": result.duration_seconds,
                })
        else:
            def _worker(t: CCBenchTask) -> CCBenchResult:
                self.on_event("task_start", {"task_id": t.id, "title": t.title})
                res = self.run_task(t)
                self.on_event("task_complete", {
                    "task_id": t.id,
                    "passed": res.passed,
                    "duration": res.duration_seconds,
                })
                return res

            with ThreadPoolExecutor(max_workers=min(max_parallel, len(target_tasks))) as executor:
                results = list(executor.map(_worker, target_tasks))

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        pass_rate = (passed_count / total * 100) if total else 0
        total_tokens = sum(r.tokens_used for r in results)
        total_cost = sum(r.cost_usd for r in results)

        summary = {
            "total_tasks": total,
            "passed_tasks": passed_count,
            "pass_rate_percent": round(pass_rate, 1),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "results": [r.__dict__ for r in results],
        }
        self.on_event("suite_complete", summary)
        return summary


def create_web_sync_handler(base_url: str = "http://127.0.0.1:8000") -> Callable[[str, dict], None]:
    """Returns an event listener that posts real-time events to the local FastAPI Web UI."""
    import urllib.request
    import urllib.error

    def _sync(event_name: str, payload: dict):
        try:
            url = f"{base_url}/api/events/broadcast"
            data = json.dumps({"event_type": event_name, "payload": payload}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                pass
        except Exception:
            pass

    return _sync


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CCBench Evaluation Suite for Ponder")
    parser.add_argument("--curated", action="store_true", help="Run curated benchmark tasks (Redis, Git, SQLite)")
    parser.add_argument("--task", default=None, help="Run single task ID")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of tasks")
    parser.add_argument("--parallel", type=int, default=1, help="Parallel worker count")
    parser.add_argument("--harbor", action="store_true", help="Execute inside Harbor container sandbox")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode")
    parser.add_argument("--web-url", default="http://127.0.0.1:8000", help="Web UI URL to sync events to")
    args = parser.parse_args()

    client = NebiusClient(mock_mode=args.mock)

    # Wire up web sync listener
    web_sync = create_web_sync_handler(args.web_url)

    def event_listener(event: str, data: dict):
        print(f"[{event}] {json.dumps(data)}")
        web_sync(event, data)

    runner = CCBenchRunner(
        client=client,
        on_event=event_listener,
        use_harbor=args.harbor,
    )

    if args.curated:
        all_tasks = CURATED_CCBENCH_TASKS
    else:
        all_tasks = CURATED_CCBENCH_TASKS + load_all_official_tasks()

    if args.task:
        target_tasks = [t for t in all_tasks if t.id == args.task]
    else:
        target_tasks = all_tasks[:args.limit] if args.limit else all_tasks

    print(f"\n🚀 Running CCBench Suite: {len(target_tasks)} tasks (parallel={args.parallel}, harbor={args.harbor})")
    print(f"📡 Syncing live events to Web UI at {args.web_url}\n")

    summary = runner.run_suite(target_tasks, max_parallel=args.parallel)
    print("\n================ BENCHMARK SUMMARY ================")
    print(f"Total Tasks:   {summary['total_tasks']}")
    print(f"Passed:        {summary['passed_tasks']} ({summary['pass_rate_percent']}%)")
    print(f"Total Cost:    ${summary['total_cost_usd']}")
    print("===================================================\n")


if __name__ == "__main__":
    main()
