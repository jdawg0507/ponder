"""FastAPI Web Server and SSE Event Broadcaster for Ponder UI."""

from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional
from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ponder.benchmarks.ccbench import (
    CURATED_CCBENCH_TASKS,
    CCBenchRunner,
    CCBenchTask,
)
from ponder.client import NebiusClient
from ponder.orchestrator import Orchestrator


app = FastAPI(title="Ponder Agent Web Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EVENT_SUBSCRIBERS: List[asyncio.Queue] = []
UI_HTML_PATH = Path(__file__).parent / "ui" / "index.html"


def broadcast_event(event_type: str, payload: dict):
    """Enqueues an event to all connected SSE clients."""
    msg = json.dumps({"type": event_type, "payload": payload})
    for queue in list(EVENT_SUBSCRIBERS):
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def get_index():
    if UI_HTML_PATH.exists():
        return UI_HTML_PATH.read_text(encoding="utf-8")
    return "<h1>Ponder Dashboard UI file not found.</h1>"


@app.get("/api/events")
async def event_stream():
    """SSE endpoint streaming live agent events to the browser."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    EVENT_SUBSCRIBERS.append(queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial keepalive
            yield f"data: {json.dumps({'type': 'connected', 'payload': {}})}\n\n"
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in EVENT_SUBSCRIBERS:
                EVENT_SUBSCRIBERS.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


class BroadcastEventRequest(BaseModel):
    event_type: str
    payload: dict


@app.post("/api/events/broadcast")
async def post_broadcast_event(req: BroadcastEventRequest):
    """Allows CLI runners or background jobs to broadcast live events to connected Web UI clients."""
    broadcast_event(req.event_type, req.payload)
    return {"status": "broadcasted"}


from ponder.benchmarks.ccbench import (
    CURATED_CCBENCH_TASKS,
    CCBenchRunner,
    CCBenchTask,
    load_all_official_tasks,
)


ALL_TASKS = load_all_official_tasks()


@app.get("/api/benchmark/tasks")
async def get_tasks(language: Optional[str] = None, track: Optional[str] = None):
    tasks = ALL_TASKS
    if language:
        tasks = [t for t in tasks if t.language.lower() == language.lower()]
    if track:
        tasks = [t for t in tasks if t.track.lower() == track.lower()]
    return [
        {
            "id": t.id,
            "title": t.title,
            "track": t.track,
            "language": t.language,
            "instructions": t.instructions[:300] + "...",
        }
        for t in tasks
    ]


@app.post("/api/benchmark/run")
async def run_benchmark_task(task_id: str = Query(...)):
    task = next((t for t in ALL_TASKS if t.id == task_id), None)
    if not task:
        return {"error": f"Task '{task_id}' not found"}


    api_key = os.environ.get("NEBIUS_API_KEY")
    client = NebiusClient(api_key=api_key)

    runner = CCBenchRunner(
        base_workspace="./ccbench_runs",
        client=client,
        on_event=broadcast_event,
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, runner.run_task, task)
    return result.__dict__


@app.get("/api/benchmark/results")
async def get_benchmark_results():
    """Returns all stored benchmark task results."""
    results_file = Path("./ccbench_runs/results.json")
    if not results_file.exists():
        results_file = Path("./ccbench_workspace/results.json")
    if results_file.exists():
        try:
            return json.loads(results_file.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


@app.post("/api/benchmark/run_suite")
async def run_benchmark_suite(
    background_tasks: BackgroundTasks,
    language: Optional[str] = None,
    track: Optional[str] = None,
    limit: Optional[int] = None,
    parallel: int = 2,
):
    api_key = os.environ.get("NEBIUS_API_KEY")
    client = NebiusClient(api_key=api_key)

    runner = CCBenchRunner(
        base_workspace="./ccbench_runs",
        client=client,
        on_event=broadcast_event,
    )

    tasks = ALL_TASKS
    if language:
        tasks = [t for t in tasks if t.language.lower() == language.lower()]
    if track:
        tasks = [t for t in tasks if t.track.lower() == track.lower()]
    if limit:
        tasks = tasks[:limit]

    # Execute in background to prevent HTTP connection timeout on long suites
    background_tasks.add_task(runner.run_suite, tasks, parallel)
    return {
        "status": "started",
        "total_tasks": len(tasks),
        "message": f"Suite execution started for {len(tasks)} tasks.",
    }


class CustomPromptRequest(BaseModel):
    requirement: str
    workspace: Optional[str] = "./custom_workspace"


@app.post("/api/agent/run")
async def run_custom_agent(req: CustomPromptRequest):
    api_key = os.environ.get("NEBIUS_API_KEY")
    client = NebiusClient(api_key=api_key)

    orchestrator = Orchestrator(
        workspace_dir=req.workspace,
        client=client,
        on_event=broadcast_event,
    )

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, orchestrator.run, req.requirement)
    return res


def start_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
