#!/usr/bin/env python3
"""Mission Control control queue manager.

Supports enqueue + processing control commands with audit output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
QUEUE_FILE = ROOT / "mission-control" / "data" / "control-queue.json"
RESULTS_FILE = ROOT / "mission-control" / "data" / "control-results.jsonl"
DAILY_TASKS = ROOT / "memory" / "daily_tasks.json"
TODO_LIST = ROOT / "memory" / "todo_list.json"
JOBS_FILE = Path("/home/pedro/.openclaw/cron/jobs.json")

DEFAULT_TZ = "America/Sao_Paulo"


def utc_now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def queue() -> list[dict[str, Any]]:
    payload = read_json(QUEUE_FILE, [])
    return payload if isinstance(payload, list) else []


def save_queue(items: list[dict[str, Any]]) -> None:
    write_json(QUEUE_FILE, items)


def run_cmd(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except Exception as exc:
        return False, f"failed to execute: {exc}"

    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    output = output.strip()
    if proc.returncode == 0:
        return True, output or "ok"
    return False, output or f"exit code {proc.returncode}"


def find_job_id_by_name(name: str) -> str | None:
    jobs = read_json(JOBS_FILE, {}).get("jobs", [])
    for job in jobs:
        if job.get("name") == name:
            return job.get("id")
    return None


def set_task_status(source: str, task_key: str, new_status: str) -> tuple[bool, str]:
    if source == "daily":
        payload = read_json(DAILY_TASKS, {})
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, dict) or task_key not in tasks:
            return False, f"task '{task_key}' not found in daily tasks"

        tasks[task_key]["status"] = new_status
        tasks[task_key]["updatedAt"] = utc_now_iso()
        if new_status == "DONE":
            tasks[task_key]["doneAt"] = utc_now_iso()
        if new_status == "SKIPPED":
            tasks[task_key]["skippedAt"] = utc_now_iso()
        write_json(DAILY_TASKS, payload)
        return True, f"daily task {task_key} marked {new_status}"

    if source == "todo":
        payload = read_json(TODO_LIST, [])
        if not isinstance(payload, list):
            return False, "todo list invalid format"

        for row in payload:
            if str(row.get("id")) == str(task_key) or str(row.get("task")) == task_key:
                row["status"] = new_status
                row["updatedAt"] = utc_now_iso()
                write_json(TODO_LIST, payload)
                return True, f"todo item {task_key} marked {new_status}"
        return False, f"todo item '{task_key}' not found"

    return False, "invalid source; expected 'daily' or 'todo'"


def set_todo_deadline(task_key: str, deadline: str) -> tuple[bool, str]:
    try:
        dt.date.fromisoformat(deadline)
    except ValueError:
        return False, "invalid deadline format; expected YYYY-MM-DD"

    payload = read_json(TODO_LIST, [])
    if not isinstance(payload, list):
        return False, "todo list invalid format"

    for row in payload:
        if str(row.get("id")) == str(task_key) or str(row.get("task")) == task_key:
            row["deadline"] = deadline
            row["updatedAt"] = utc_now_iso()
            write_json(TODO_LIST, payload)
            return True, f"todo item {task_key} deadline set to {deadline}"

    return False, f"todo item '{task_key}' not found"


def run_all_failed_crons() -> tuple[bool, str]:
    jobs = read_json(JOBS_FILE, {}).get("jobs", [])
    failed_ids = []
    for job in jobs:
        state = job.get("state") or {}
        if state.get("lastStatus") == "error" or int(state.get("consecutiveErrors") or 0) > 0:
            if job.get("id"):
                failed_ids.append(str(job.get("id")))

    if not failed_ids:
        return True, "no failed cron jobs"

    outputs = []
    ok_all = True
    for job_id in failed_ids:
        ok, message = run_cmd(["openclaw", "cron", "run", job_id])
        ok_all = ok_all and ok
        outputs.append(f"{job_id}: {'ok' if ok else 'error'}")
        if message:
            outputs.append(message)

    return ok_all, "\n".join(outputs)


def execute_command(command: dict[str, Any]) -> tuple[bool, str]:
    action = command.get("action")
    payload = command.get("payload") or {}

    if action == "cron.retry":
        job_id = payload.get("jobId")
        if not job_id:
            return False, "missing payload.jobId"
        return run_cmd(["openclaw", "cron", "run", str(job_id)])

    if action == "cron.pause":
        job_id = payload.get("jobId")
        if not job_id:
            return False, "missing payload.jobId"
        return run_cmd(["openclaw", "cron", "disable", str(job_id)])

    if action == "cron.resume":
        job_id = payload.get("jobId")
        if not job_id:
            return False, "missing payload.jobId"
        return run_cmd(["openclaw", "cron", "enable", str(job_id)])

    if action == "cron.set_timezone":
        job_id = payload.get("jobId")
        tz = str(payload.get("tz") or DEFAULT_TZ)
        if not job_id:
            return False, "missing payload.jobId"
        return run_cmd(["openclaw", "cron", "edit", str(job_id), "--tz", tz])

    if action == "cron.run_all_failed":
        return run_all_failed_crons()

    if action == "digest.retry_send":
        job_id = payload.get("jobId") or find_job_id_by_name("Diário da Família - Enviador")
        if not job_id:
            return False, "could not resolve digest sender job id"
        return run_cmd(["openclaw", "cron", "run", str(job_id)])

    if action == "task.mark_done":
        source = str(payload.get("source") or "")
        task_key = str(payload.get("taskKey") or "")
        if not source or not task_key:
            return False, "missing payload.source or payload.taskKey"
        return set_task_status(source=source, task_key=task_key, new_status="DONE")

    if action == "task.mark_skipped":
        source = str(payload.get("source") or "")
        task_key = str(payload.get("taskKey") or "")
        if not source or not task_key:
            return False, "missing payload.source or payload.taskKey"
        return set_task_status(source=source, task_key=task_key, new_status="SKIPPED")

    if action == "todo.set_deadline":
        task_key = str(payload.get("taskKey") or "").strip()
        deadline = str(payload.get("deadline") or "").strip()
        if not task_key or not deadline:
            return False, "missing payload.taskKey or payload.deadline"
        if task_key == "__none__":
            return False, "invalid payload.taskKey: __none__"
        return set_todo_deadline(task_key=task_key, deadline=deadline)

    return False, f"unsupported action: {action}"


def enqueue(action: str, payload: dict[str, Any], requested_by: str) -> dict[str, Any]:
    items = queue()
    cmd = {
        "commandId": str(uuid.uuid4()),
        "createdAt": utc_now_iso(),
        "requestedBy": requested_by,
        "status": "queued",
        "action": action,
        "payload": payload,
    }
    items.append(cmd)
    save_queue(items)
    return cmd


def process(max_items: int) -> list[dict[str, Any]]:
    items = queue()
    processed: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for item in items:
        if len(processed) >= max_items:
            remaining.append(item)
            continue

        if item.get("status") not in {"queued", "retry"}:
            remaining.append(item)
            continue

        ok, message = execute_command(item)
        result = {
            "commandId": item.get("commandId"),
            "executedAt": utc_now_iso(),
            "executor": "mission-control/scripts/control_queue.py",
            "action": item.get("action"),
            "payload": item.get("payload") or {},
            "result": "ok" if ok else "error",
            "message": message,
        }
        append_jsonl(RESULTS_FILE, result)
        processed.append(result)

    save_queue(remaining)
    return processed


def parse_kv_payload(pairs: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"invalid --payload entry '{pair}', expected k=v")
        key, value = pair.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def cmd_enqueue(args: argparse.Namespace) -> int:
    try:
        payload = parse_kv_payload(args.payload or [])
    except ValueError as exc:
        print(str(exc))
        return 2

    row = enqueue(action=args.action, payload=payload, requested_by=args.requested_by)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    rows = process(max_items=args.max_items)
    print(json.dumps({"processed": len(rows), "results": rows}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    items = queue()
    print(json.dumps({"count": len(items), "queue": items}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mission Control control queue")
    sub = parser.add_subparsers(dest="command", required=True)

    p_enqueue = sub.add_parser("enqueue", help="enqueue a control command")
    p_enqueue.add_argument("--action", required=True, help="Action name (e.g. cron.retry)")
    p_enqueue.add_argument("--payload", action="append", help="Payload entry as k=v (repeatable)")
    p_enqueue.add_argument("--requested-by", default="dashboard", help="Requester id")
    p_enqueue.set_defaults(func=cmd_enqueue)

    p_process = sub.add_parser("process", help="process queued commands")
    p_process.add_argument("--max-items", type=int, default=10)
    p_process.set_defaults(func=cmd_process)

    p_list = sub.add_parser("list", help="list pending queue")
    p_list.set_defaults(func=cmd_list)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
