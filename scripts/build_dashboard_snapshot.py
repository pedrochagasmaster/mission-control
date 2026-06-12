#!/usr/bin/env python3
"""Build Mission Control dashboard snapshots (v3 + compatibility outputs)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from workflow_ledger_v2 import reconcile_from_ledgers, sync_workflow_ledgers

ROOT = Path(__file__).resolve().parents[2]
OPENCLAW_JOBS = Path("/home/pedro/.openclaw/cron/jobs.json")

DEFAULT_V3_OUTPUT = ROOT / "mission-control" / "data" / "dashboard-data.v3.json"
V2_OUTPUT = ROOT / "mission-control" / "data" / "dashboard-data.v2.json"
LEGACY_OUTPUT = ROOT / "mission-control" / "data" / "dashboard-data.json"
HISTORY_DIR = ROOT / "mission-control" / "data" / "history"

QUEUE_FILE = ROOT / "mission-control" / "data" / "control-queue.json"
RESULTS_FILE = ROOT / "mission-control" / "data" / "control-results.jsonl"

DAILY_TASKS = ROOT / "memory" / "daily_tasks.json"
TODO_LIST = ROOT / "memory" / "todo_list.json"
DIGEST_DRAFT = ROOT / "memory" / "daily_digest_draft.json"
DIGEST_SENT_LOG = ROOT / "memory" / "digest_sent.log"
EVENTS_DIR = ROOT / "memory" / "events"
THERAPY_DIR = ROOT / "memory" / "therapy"
KNOWLEDGE_DIR = ROOT / "knowledge"
HEARTBEAT_FILE = ROOT / "HEARTBEAT.md"

PLUGGY_DIR = ROOT / "pluggy"
OPENBANKING_DIR = ROOT / "openbanking"
BANK_MONITOR_LOG = ROOT / "logs" / "bank_monitor.log"
CREDENTIALS_DIR = Path("/home/pedro/.openclaw/credentials")

MISSION_CONTROL_URL = "https://pedrochagasmaster.github.io/mission-control/"
COMMAND_TIMEOUT_SECONDS = 5


WORKFLOW_LEDGER_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "digest": {
        "name": "Digest",
        "jobs": [
            "Diário da Família - Gerador",
            "Diário da Família - Enviador",
            "Diário da Família - Watchdog (fallback)",
            "Diário da Família - Watchdog (retry 08:15)",
            "Diário da Família - Alert (07:50 se não enviado)",
        ],
        "canonicalChannel": "whatsapp",
        "successChannel": "whatsapp",
        "fallbackChannels": ["telegram"],
        "deliveryRequired": True,
    },
    "pluggy": {
        "name": "Pluggy",
        "jobs": ["Pluggy Sync - Tracking Despesas"],
        "canonicalChannel": "whatsapp",
        "successChannel": "whatsapp",
        "fallbackChannels": ["telegram"],
        "deliveryRequired": True,
    },
    "reminders": {
        "name": "Reminders",
        "jobs": ["Deadline Reminder Checker", "Resumo Diário da To-Do List"],
        "canonicalChannel": "whatsapp",
        "successChannel": "whatsapp",
        "fallbackChannels": ["telegram"],
        "deliveryRequired": True,
    },
    "routines": {
        "name": "Rotinas",
        "jobs": [
            "Rotina da Manhã (Completa)",
            "Ração Almoço",
            "Passeio Almoço",
            "Pós-Almoço: Zero Pia",
            "Blitz da Ordem (17:30)",
            "Rotina da Tarde",
            "Rotina da Noite (Completa)",
        ],
        "canonicalChannel": "whatsapp",
        "successChannel": "whatsapp",
        "fallbackChannels": ["telegram"],
        "deliveryRequired": True,
    },
    "proactive_group": {
        "name": "Proactive Group",
        "jobs": ["Pulso Familiar - Meio-dia", "Pulso Familiar - Noite"],
        "canonicalChannel": "whatsapp",
        "successChannel": "whatsapp",
        "fallbackChannels": ["telegram"],
        "deliveryRequired": True,
    },
    "tracking_watchdog": {
        "name": "Tracking Watchdog",
        "jobs": ["Watchdog - Tracking Despesas (API + Frontend)"],
        "canonicalChannel": None,
        "successChannel": None,
        "fallbackChannels": [],
        "deliveryRequired": False,
    },
    "mission_control": {
        "name": "Mission Control",
        "jobs": ["Mission Control - Control Runner", "Mission Control - Build+Publish"],
        "canonicalChannel": None,
        "successChannel": None,
        "fallbackChannels": [],
        "deliveryRequired": False,
    },
}


def now_utc() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if limit is not None:
        return rows[-limit:]
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_iso_from_ms(ms: Any) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).isoformat()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def mode_str(path: Path) -> str:
    try:
        return oct(path.stat().st_mode & 0o777)[2:]
    except Exception:
        return "unknown"


def run_json_command(cmd: list[str]) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None

    if proc.returncode != 0:
        return None

    start = proc.stdout.find("{")
    if start < 0:
        return None

    try:
        return json.loads(proc.stdout[start:])
    except json.JSONDecodeError:
        return None


def run_text_command(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return False, ""
    except subprocess.TimeoutExpired as exc:
        return False, f"command timed out after {exc.timeout} seconds: {' '.join(map(str, cmd))}"

    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode == 0, out.strip()


def load_crons() -> list[dict[str, Any]]:
    live = run_json_command(["openclaw", "cron", "list", "--json"])
    if live and isinstance(live.get("jobs"), list):
        return live["jobs"]

    local = read_json(OPENCLAW_JOBS, {})
    if isinstance(local.get("jobs"), list):
        return local["jobs"]
    return []


def load_sessions(active_minutes: int = 180) -> list[dict[str, Any]]:
    live = run_json_command(
        [
            "openclaw",
            "sessions",
            "--active",
            str(active_minutes),
            "--all-agents",
            "--json",
        ]
    )
    if live and isinstance(live.get("sessions"), list):
        return live["sessions"]
    return []


def has_tz_mismatch(job: dict[str, Any]) -> bool:
    schedule = job.get("schedule") or {}
    if schedule.get("kind") != "cron":
        return False
    expr = str(schedule.get("expr") or "")
    if not expr:
        return False
    return not schedule.get("tz")


def normalize_cron(job: dict[str, Any]) -> dict[str, Any]:
    state = job.get("state") or {}
    schedule = job.get("schedule") or {}
    enabled = bool(job.get("enabled", True))
    errors = safe_int(state.get("consecutiveErrors"))

    if not enabled:
        status = "paused"
    elif state.get("lastStatus") == "error" or errors > 0:
        status = "error"
    else:
        status = "ok"

    parts = [str(schedule.get("expr") or "").strip()]
    if schedule.get("tz"):
        parts.append(f"({schedule['tz']})")

    return {
        "id": job.get("id"),
        "name": job.get("name") or "(sem nome)",
        "status": status,
        "enabled": enabled,
        "errors": errors,
        "lastError": state.get("lastError") or state.get("lastDeliveryError"),
        "lastRun": format_iso_from_ms(state.get("lastRunAtMs")),
        "nextRun": format_iso_from_ms(state.get("nextRunAtMs")),
        "schedule": " ".join([p for p in parts if p]),
        "tzMissing": has_tz_mismatch(job),
        "model": (job.get("payload") or {}).get("model"),
        "channel": (job.get("delivery") or {}).get("channel"),
    }


def load_today_events(limit: int = 50) -> list[dict[str, Any]]:
    if not EVENTS_DIR.exists():
        return []

    today = dt.datetime.now().date().isoformat()
    rows = read_jsonl(EVENTS_DIR / f"{today}.jsonl", limit=limit)
    events: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get("local_timestamp") or row.get("timestamp")
        text = row.get("text")
        if ts and text:
            events.append({"time": ts, "event": text, "channel": row.get("channel")})
    return events


def load_active_sessions(sessions: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session in sessions:
        key = str(session.get("key") or "")
        if not key or ":run:" in key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "task": key,
                "model": session.get("model"),
                "startedAt": format_iso_from_ms(session.get("updatedAt")),
                "agentId": session.get("agentId"),
                "kind": session.get("kind"),
            }
        )
    return out[:limit]


def build_routines_domain() -> dict[str, Any]:
    payload = read_json(DAILY_TASKS, {})
    tasks = payload.get("tasks") if isinstance(payload, dict) else {}

    pending = 0
    done = 0
    skipped = 0
    overdue = 0
    now_local = dt.datetime.now().strftime("%H:%M")

    rows: list[dict[str, Any]] = []
    # Handle both dict and list formats for tasks
    if isinstance(tasks, list):
        task_iter = [(t.get("id", f"task_{i}"), t) for i, t in enumerate(tasks)]
    else:
        task_iter = (tasks or {}).items()
    for key, task in task_iter:
        status = (task or {}).get("status") or "UNKNOWN"
        label = (task or {}).get("label") or key
        hhmm = (task or {}).get("time")
        if status == "PENDING":
            pending += 1
            if isinstance(hhmm, str) and hhmm <= now_local:
                overdue += 1
        elif status == "DONE":
            done += 1
        elif status == "SKIPPED":
            skipped += 1
        rows.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "time": hhmm,
                "note": (task or {}).get("note", ""),
                "name": (task or {}).get("name", ""),
            }
        )

    return {
        "id": "routines",
        "name": "Rotinas da Casa",
        "status": "warning" if overdue > 0 else "ok",
        "kpis": {
            "pending": pending,
            "done": done,
            "skipped": skipped,
            "overdue": overdue,
        },
        "tasks": sorted(rows, key=lambda row: (row.get("time") or "99:99", row["label"])),
        "alerts": [
            {"level": "warning", "text": f"{overdue} tarefa(s) pendente(s) já no horário"}
        ]
        if overdue
        else [],
        "actions": ["task.mark_done", "task.mark_skipped"],
        "source": str(DAILY_TASKS),
    }


def build_todo_domain() -> dict[str, Any]:
    rows = read_json(TODO_LIST, [])
    if not isinstance(rows, list):
        rows = []

    pending_items = [row for row in rows if row.get("status") == "PENDING"]
    done_items = [row for row in rows if row.get("status") == "DONE"]

    overdue = 0
    risk_72h = 0
    today = dt.datetime.now().date()
    in_72h = today + dt.timedelta(days=3)

    for row in pending_items:
        deadline = row.get("deadline")
        if not deadline:
            continue
        try:
            due = dt.date.fromisoformat(deadline)
        except ValueError:
            continue
        if due < today:
            overdue += 1
        if today <= due <= in_72h:
            risk_72h += 1

    return {
        "id": "todo",
        "name": "To-Do Geral",
        "status": "warning" if overdue > 0 else "ok",
        "kpis": {
            "pending": len(pending_items),
            "done": len(done_items),
            "overdue": overdue,
            "risk72h": risk_72h,
            "total": len(rows),
        },
        "items": pending_items[:12],
        "alerts": [{"level": "warning", "text": f"{overdue} item(ns) vencido(s)"}] if overdue else [],
        "actions": ["task.mark_done", "todo.set_deadline"],
        "source": str(TODO_LIST),
    }


def build_digest_domain(crons_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    related_names = [
        "Diário da Família - Gerador",
        "Diário da Família - Enviador",
        "Diário da Família - Watchdog (fallback)",
        "Diário da Família - Watchdog (retry 08:15)",
        "Diário da Família - Alert (07:50 se não enviado)",
    ]
    related = [crons_by_name[name] for name in related_names if name in crons_by_name]
    error_jobs = [job for job in related if job.get("status") == "error"]

    today = dt.datetime.now().date().isoformat()
    sent_today = False
    if DIGEST_SENT_LOG.exists():
        for line in DIGEST_SENT_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip() == today:
                sent_today = True
                break

    draft = read_json(DIGEST_DRAFT, {})
    draft_date = draft.get("date") if isinstance(draft, dict) else None
    draft_ok = draft_date == today

    status = "ok"
    if error_jobs:
        status = "error"
    elif not sent_today and dt.datetime.now().hour >= 8:
        status = "warning"

    return {
        "id": "digest",
        "name": "Diário da Família",
        "status": status,
        "kpis": {
            "sentToday": sent_today,
            "draftReady": bool(draft_ok),
            "errorJobs": len(error_jobs),
            "pipelineStages": len(related),
        },
        "pipeline": related,
        "draft": {"date": draft_date, "tema": draft.get("tema") if isinstance(draft, dict) else None},
        "alerts": [{"level": "high", "text": f"{len(error_jobs)} job(s) com erro no pipeline"}] if error_jobs else [],
        "actions": ["digest.retry_send", "cron.retry"],
        "source": str(DIGEST_DRAFT),
    }


def build_crons_domain(crons: list[dict[str, Any]]) -> dict[str, Any]:
    error_count = len([c for c in crons if c["status"] == "error"])
    paused_count = len([c for c in crons if c["status"] == "paused"])
    tz_missing = len([c for c in crons if c.get("tzMissing")])

    status = "ok"
    if error_count > 0:
        status = "error"
    elif tz_missing > 0 or paused_count > 0:
        status = "warning"

    alerts = []
    if error_count:
        alerts.append({"level": "high", "text": f"{error_count} cron(s) em erro"})
    if tz_missing:
        alerts.append({"level": "warning", "text": f"{tz_missing} cron(s) sem timezone"})

    return {
        "id": "crons",
        "name": "Cron Jobs",
        "status": status,
        "kpis": {
            "total": len(crons),
            "errors": error_count,
            "paused": paused_count,
            "tzMissing": tz_missing,
        },
        "jobs": crons,
        "alerts": alerts,
        "actions": ["cron.retry", "cron.pause", "cron.resume", "cron.set_timezone"],
        "source": str(OPENCLAW_JOBS),
    }


def parse_systemd_status(service: str) -> dict[str, Any]:
    ok, text = run_text_command(["systemctl", "status", service, "--no-pager"])
    active = False
    since = None
    if text:
        m = re.search(r"Active:\s+([^(]+)\(running\) since (.*?);", text)
        if m:
            active = m.group(1).strip().startswith("active")
            since = m.group(2).strip()
    return {"service": service, "active": active and ok, "since": since, "raw": text if not ok else None}


def file_mtime(path: Path) -> str | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).isoformat()
    except Exception:
        return None


def build_integrations(crons_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    knowledge_service = parse_systemd_status("knowledge-watcher.service")

    pluggy_items = read_json(PLUGGY_DIR / "tracked_items.json", [])
    if not isinstance(pluggy_items, list):
        pluggy_items = []

    openbanking_config_files = sorted((OPENBANKING_DIR / "config").glob("*.json")) if OPENBANKING_DIR.exists() else []
    openbanking_tokens = sorted((OPENBANKING_DIR / "tokens").glob("*")) if OPENBANKING_DIR.exists() else []

    pluggy_job = crons_by_name.get("Pluggy Sync - Tracking Despesas")
    openbanking_job = None
    for cron in crons_by_name.values():
        if "openbanking" in cron.get("name", "").lower():
            openbanking_job = cron
            break

    bank_monitor_enabled = BANK_MONITOR_LOG.exists()

    def status_from_cron(job: dict[str, Any] | None) -> str:
        if not job:
            return "warning"
        return "ok" if job.get("status") == "ok" else "error"

    return {
        "pluggy": {
            "status": status_from_cron(pluggy_job),
            "trackedItems": len(pluggy_items),
            "lastLogAt": file_mtime(PLUGGY_DIR / "logs" / "pluggy.log"),
            "job": pluggy_job,
        },
        "openbanking": {
            "status": "warning" if openbanking_job is None else status_from_cron(openbanking_job),
            "configFiles": len(openbanking_config_files),
            "tokenFiles": len(openbanking_tokens),
            "lastSyncAt": file_mtime(OPENBANKING_DIR / "logs" / "sync.log"),
            "job": openbanking_job,
        },
        "bank_notifications": {
            "status": "ok" if bank_monitor_enabled else "warning",
            "logEnabled": bank_monitor_enabled,
            "lastEventAt": file_mtime(BANK_MONITOR_LOG),
        },
        "knowledge_watcher": {
            "status": "ok" if knowledge_service.get("active") else "error",
            "service": knowledge_service,
            "lastKnowledgeFileAt": file_mtime(max(KNOWLEDGE_DIR.glob("*.md"), default=KNOWLEDGE_DIR) if KNOWLEDGE_DIR.exists() else KNOWLEDGE_DIR),
        },
    }


def build_knowledge_domain(crons_by_name: dict[str, dict[str, Any]], integrations: dict[str, Any]) -> dict[str, Any]:
    ingest = crons_by_name.get("Instagram Knowledge Ingest")
    files = sorted(KNOWLEDGE_DIR.glob("*.md")) if KNOWLEDGE_DIR.exists() else []
    last_file = files[-1].name if files else None

    watcher_status = integrations.get("knowledge_watcher", {}).get("status")
    status = "ok" if ingest and ingest.get("status") == "ok" and watcher_status == "ok" else "warning"

    return {
        "id": "knowledge",
        "name": "Knowledge Parental",
        "status": status,
        "kpis": {
            "files": len(files),
            "ingestHealthy": bool(ingest and ingest.get("status") == "ok"),
            "watcherHealthy": watcher_status == "ok",
        },
        "lastFile": last_file,
        "job": ingest,
        "actions": ["cron.retry"],
        "source": str(KNOWLEDGE_DIR),
    }


def recent_event_rows(limit: int = 400) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not EVENTS_DIR.exists():
        return rows
    for path in sorted(EVENTS_DIR.glob("*.jsonl"))[-7:]:
        rows.extend(read_jsonl(path, limit=None))
    return rows[-limit:]


def workflow_truth_status(info: dict[str, Any]) -> tuple[str, int, list[str]]:
    reasons: list[str] = []
    score = 100
    jobs = info.get("jobs") or []
    expected_channel = info.get("successChannel")
    fallback_channels = set(info.get("fallbackChannels") or [])
    delivery_required = bool(info.get("deliveryRequired"))

    if not jobs:
        return "broken", 15, ["sem jobs mapeados"]

    broken_jobs = [j for j in jobs if j.get("status") == "error"]
    if broken_jobs:
        reasons.append(f"{len(broken_jobs)} job(s) em erro")
        return "broken", max(15, 100 - (20 * len(broken_jobs))), reasons

    lying_risk = []
    degraded = []
    healthy = []

    for job in jobs:
        state = job.get("state") or {}
        delivery_status = state.get("lastDeliveryStatus") or job.get("lastDeliveryStatus")
        delivered = state.get("lastDelivered") if isinstance(state.get("lastDelivered"), bool) else job.get("lastDelivered")
        channel = (job.get("delivery") or {}).get("channel") or job.get("channel")
        last_run = state.get("lastRunAtMs") or job.get("lastRunAtMs")

        if delivery_required:
            if delivery_status == "not-delivered" or delivered is False:
                lying_risk.append(job)
                continue
            if expected_channel and channel and channel != expected_channel:
                if channel in fallback_channels:
                    degraded.append(job)
                    continue
                degraded.append(job)
                continue
            if not channel:
                degraded.append(job)
                continue
        if not last_run:
            degraded.append(job)
            continue
        healthy.append(job)

    if lying_risk:
        reasons.append(f"{len(lying_risk)} job(s) reportaram execução sem entrega válida")
        score -= 35 + (5 * (len(lying_risk) - 1))
        return "lying-risk", max(20, score), reasons

    if degraded:
        if expected_channel:
            fallback_list = ", ".join(sorted({((j.get('delivery') or {}).get('channel') or j.get('channel') or 'sem-canal') for j in degraded}))
            reasons.append(f"entrega degradada via {fallback_list}")
        else:
            reasons.append(f"{len(degraded)} job(s) com evidência incompleta")
        score -= 18 + (4 * (len(degraded) - 1))
        return "degraded", max(35, score), reasons

    reasons.append("execução e entrega alinhadas com o canal canônico")
    return "healthy", score, reasons


def build_workflow_truth(raw_crons: list[dict[str, Any]], recent_events: list[dict[str, Any]]) -> dict[str, Any]:
    raw_by_name = {str(job.get('name') or ''): job for job in raw_crons}
    pipelines: list[dict[str, Any]] = []
    counts = {"healthy": 0, "degraded": 0, "lying-risk": 0, "broken": 0}

    for workflow_id, spec in WORKFLOW_LEDGER_EXPECTATIONS.items():
        jobs = []
        matched_ids = []
        for name in spec.get('jobs', []):
            raw_job = raw_by_name.get(name)
            if raw_job:
                jobs.append(raw_job)
                if raw_job.get('id'):
                    matched_ids.append(str(raw_job['id']))

        status, confidence, reasons = workflow_truth_status({**spec, 'jobs': jobs})
        counts[status] += 1

        event_count = 0
        last_event = None
        if matched_ids:
            for row in recent_events:
                chat_id = str(row.get('chat_id') or '')
                if any(job_id in chat_id for job_id in matched_ids):
                    event_count += 1
                    last_event = row.get('local_timestamp') or row.get('timestamp') or last_event

        pipelines.append({
            'id': workflow_id,
            'name': spec['name'],
            'status': status,
            'confidence': confidence,
            'canonicalChannel': spec.get('canonicalChannel'),
            'deliveryRequired': bool(spec.get('deliveryRequired')),
            'jobs': [
                {
                    'id': job.get('id'),
                    'name': job.get('name'),
                    'status': normalize_cron(job).get('status'),
                    'channel': (job.get('delivery') or {}).get('channel'),
                    'lastRun': format_iso_from_ms((job.get('state') or {}).get('lastRunAtMs')),
                    'lastDeliveryStatus': (job.get('state') or {}).get('lastDeliveryStatus'),
                    'lastDelivered': (job.get('state') or {}).get('lastDelivered'),
                }
                for job in jobs
            ],
            'signals': {
                'jobCount': len(jobs),
                'eventCount': event_count,
                'lastEvent': last_event,
            },
            'reasons': reasons,
        })

    overall = 'healthy'
    if counts['broken']:
        overall = 'broken'
    elif counts['lying-risk']:
        overall = 'lying-risk'
    elif counts['degraded']:
        overall = 'degraded'

    return {
        'status': overall,
        'counts': counts,
        'pipelines': pipelines,
    }


def build_finance_domain(integrations: dict[str, Any]) -> dict[str, Any]:
    pluggy_status = integrations.get("pluggy", {}).get("status")
    openbanking_status = integrations.get("openbanking", {}).get("status")
    bank_status = integrations.get("bank_notifications", {}).get("status")

    status = "ok"
    if "error" in {pluggy_status, openbanking_status, bank_status}:
        status = "error"
    elif "warning" in {pluggy_status, openbanking_status, bank_status}:
        status = "warning"

    return {
        "id": "finance",
        "name": "Finanças (Saúde + Volume)",
        "status": status,
        "kpis": {
            "pluggyTrackedItems": integrations.get("pluggy", {}).get("trackedItems", 0),
            "openbankingConfigs": integrations.get("openbanking", {}).get("configFiles", 0),
            "bankNotifLog": integrations.get("bank_notifications", {}).get("logEnabled", False),
        },
        "integrations": {
            "pluggy": integrations.get("pluggy"),
            "openbanking": integrations.get("openbanking"),
            "bank_notifications": integrations.get("bank_notifications"),
        },
        "actions": ["cron.retry"],
        "source": str(PLUGGY_DIR),
    }


def build_therapy_domain() -> dict[str, Any]:
    files = sorted([p for p in THERAPY_DIR.glob("*.md") if p.name != "INDEX.md"]) if THERAPY_DIR.exists() else []
    latest = files[-1].name if files else None

    insecure = []
    for path in files:
        try:
            mode = path.stat().st_mode & 0o777
            if mode != 0o600:
                insecure.append({"file": path.name, "mode": oct(mode)[2:]})
        except Exception:
            continue

    status = "warning" if insecure else "ok"

    return {
        "id": "therapy",
        "name": "Terapia (Privado)",
        "status": status,
        "kpis": {
            "entriesFiles": len(files),
            "latestFile": latest,
            "contentExposed": False,
            "insecurePerms": len(insecure),
        },
        "alerts": [{"level": "warning", "text": f"{len(insecure)} arquivo(s) com permissão insegura"}] if insecure else [],
        "details": {"permissions": insecure},
        "actions": [],
        "source": str(THERAPY_DIR),
    }


def parse_openclaw_status_summary() -> dict[str, Any]:
    ok, text = run_text_command(["openclaw", "status"])
    critical = 0
    warnings = 0
    info = 0

    if text:
        m = re.search(r"Summary:\s*(\d+) critical\s*·\s*(\d+) warn\s*·\s*(\d+) info", text)
        if m:
            critical = safe_int(m.group(1))
            warnings = safe_int(m.group(2))
            info = safe_int(m.group(3))

    return {
        "ok": ok,
        "critical": critical,
        "warnings": warnings,
        "info": info,
        "raw": text if not ok else None,
    }


def build_security_domain() -> dict[str, Any]:
    status_summary = parse_openclaw_status_summary()

    creds_mode = mode_str(CREDENTIALS_DIR)
    therapy_mode = mode_str(THERAPY_DIR) if THERAPY_DIR.exists() else "missing"

    alerts = []
    if status_summary["critical"] > 0:
        alerts.append({"level": "high", "text": f"{status_summary['critical']} alerta(s) crítico(s) no security audit"})
    if creds_mode not in {"700"}:
        alerts.append({"level": "high", "text": f"credentials com permissão {creds_mode} (esperado 700)"})
    if therapy_mode not in {"700", "750", "755"}:
        alerts.append({"level": "warning", "text": f"diretório therapy com permissão {therapy_mode}"})

    domain_status = "ok"
    if any(a["level"] == "high" for a in alerts):
        domain_status = "error"
    elif alerts:
        domain_status = "warning"

    return {
        "id": "security",
        "name": "Segurança e Hardening",
        "status": domain_status,
        "kpis": {
            "critical": status_summary["critical"],
            "warnings": status_summary["warnings"],
            "credentialsMode": creds_mode,
            "therapyDirMode": therapy_mode,
        },
        "alerts": alerts,
        "actions": [],
        "source": "openclaw status",
    }


def build_ops_domain(crons_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    git_job = crons_by_name.get("daily-git-commit")

    ok, ps_output = run_text_command(["bash", "-lc", "ps aux | grep -E 'rclone|notify_progress.py' | grep -v grep"])
    heartbeat_backup_ok = ok and bool(ps_output.strip())

    status = "ok" if git_job and git_job.get("status") == "ok" else "warning"
    if not heartbeat_backup_ok:
        status = "warning"

    return {
        "id": "ops",
        "name": "Monitoramento e Auditoria",
        "status": status,
        "kpis": {
            "eventsToday": len(load_today_events(limit=400)),
            "queuePending": len(read_json(QUEUE_FILE, [])),
            "heartbeatBackup": heartbeat_backup_ok,
            "heartbeatConfigured": HEARTBEAT_FILE.exists(),
        },
        "job": git_job,
        "heartbeat": {"backupProcessFound": heartbeat_backup_ok},
        "actions": [],
        "source": str(EVENTS_DIR),
    }


def load_recent_control_results(limit: int = 60) -> list[dict[str, Any]]:
    return read_jsonl(RESULTS_FILE, limit=limit)


def build_controls_catalog() -> list[dict[str, Any]]:
    return [
        {"action": "cron.retry", "title": "Retry Cron", "payloadSchema": {"jobId": "string"}},
        {"action": "cron.pause", "title": "Pause Cron", "payloadSchema": {"jobId": "string"}},
        {"action": "cron.resume", "title": "Resume Cron", "payloadSchema": {"jobId": "string"}},
        {
            "action": "cron.set_timezone",
            "title": "Set Cron Timezone",
            "payloadSchema": {"jobId": "string", "tz": "string (default America/Sao_Paulo)"},
        },
        {
            "action": "task.mark_done",
            "title": "Marcar tarefa DONE",
            "payloadSchema": {"source": "daily|todo", "taskKey": "string"},
        },
        {
            "action": "task.mark_skipped",
            "title": "Marcar tarefa SKIPPED",
            "payloadSchema": {"source": "daily|todo", "taskKey": "string"},
        },
        {
            "action": "todo.set_deadline",
            "title": "Definir deadline do To-Do",
            "payloadSchema": {"taskKey": "string|id", "deadline": "YYYY-MM-DD"},
        },
        {
            "action": "digest.retry_send",
            "title": "Retry Digest Send",
            "payloadSchema": {"jobId": "string (optional)"},
        },
    ]


def build_action_required(crons: list[dict[str, Any]], security_domain: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for cron in crons:
        if cron["status"] == "error":
            level = "high" if cron["errors"] >= 3 else "medium"
            suffix = f" ({cron['errors']} erros)" if cron["errors"] else ""
            detail = f" - {cron['lastError']}" if cron.get("lastError") else ""
            items.append(
                {
                    "type": "cron-error",
                    "targetId": cron["id"],
                    "title": f"{cron['name']}{suffix}{detail}",
                    "priority": level,
                    "actions": ["cron.retry", "cron.pause"],
                }
            )

        if cron.get("tzMissing"):
            items.append(
                {
                    "type": "cron-tz-missing",
                    "targetId": cron["id"],
                    "title": f"{cron['name']}: schedule sem timezone configurado",
                    "priority": "medium",
                    "actions": ["cron.set_timezone"],
                }
            )

    for alert in security_domain.get("alerts", []):
        items.append(
            {
                "type": "security",
                "targetId": "security",
                "title": alert.get("text"),
                "priority": "high" if alert.get("level") == "high" else "medium",
                "actions": [],
            }
        )

    return sorted(items, key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(item["priority"], 3))


def score_health(action_required: list[dict[str, Any]], domains: list[dict[str, Any]]) -> int:
    score = 100
    for item in action_required:
        score -= 15 if item.get("priority") == "high" else 8
    for domain in domains:
        status = domain.get("status")
        if status == "error":
            score -= 10
        elif status == "warning":
            score -= 4
    return max(0, min(100, score))


def list_recent_history_snapshots(days: int = 7) -> list[Path]:
    if not HISTORY_DIR.exists():
        return []

    paths: list[Path] = []
    today = dt.datetime.now().date()
    for i in range(days):
        day = (today - dt.timedelta(days=i)).isoformat()
        day_dir = HISTORY_DIR / day
        if not day_dir.exists():
            continue
        latest = day_dir / "latest.json"
        if latest.exists():
            paths.append(latest)
        else:
            candidates = sorted(day_dir.glob("snapshot-*.json"))
            if candidates:
                paths.append(candidates[-1])
    return sorted(paths)


def build_trend_payload(current: dict[str, Any], history_rows: list[dict[str, Any]]) -> dict[str, Any]:
    current_kpis = current.get("kpis") or {}
    if not history_rows:
        return {"metric": None, "delta": 0, "direction": "flat"}

    oldest = history_rows[0]
    old_kpis = (oldest.get("kpis") or {}) if isinstance(oldest, dict) else {}

    metric = None
    delta = 0
    for key, value in current_kpis.items():
        if isinstance(value, (int, float)) and isinstance(old_kpis.get(key), (int, float)):
            metric = key
            delta = value - old_kpis.get(key, 0)
            break

    direction = "flat"
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"

    return {"metric": metric, "delta": delta, "direction": direction}


def attach_trends(domains: list[dict[str, Any]]) -> None:
    history_paths = list_recent_history_snapshots(days=7)
    history = [read_json(path, {}) for path in history_paths]

    history_by_domain: dict[str, list[dict[str, Any]]] = {}
    for snap in history:
        for domain in snap.get("domains", []):
            did = domain.get("id")
            if did:
                history_by_domain.setdefault(did, []).append(domain)

    for domain in domains:
        did = domain.get("id")
        domain["trend7d"] = build_trend_payload(domain, history_by_domain.get(did, []))


def compute_slo(crons: list[dict[str, Any]], results: list[dict[str, Any]], domains: list[dict[str, Any]]) -> dict[str, Any]:
    digest_domain = next((d for d in domains if d.get("id") == "digest"), {})
    sent_today = bool((digest_domain.get("kpis") or {}).get("sentToday"))

    cron_total = len(crons)
    cron_ok = len([c for c in crons if c.get("status") == "ok"])
    cron_success_rate = round((cron_ok / cron_total) * 100, 2) if cron_total else 0.0

    action_total = len(results)
    action_ok = len([r for r in results if r.get("result") == "ok"])
    action_success = round((action_ok / action_total) * 100, 2) if action_total else 100.0

    return {
        "digest_before_0750": 100.0 if sent_today else 0.0,
        "cron_success_rate": cron_success_rate,
        "control_action_success_rate": action_success,
        "windowDays": 7,
    }


def persist_history(snapshot: dict[str, Any]) -> None:
    now = dt.datetime.now()
    day_dir = HISTORY_DIR / now.date().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    stamp = now.strftime("snapshot-%H%M%S.json")
    write_json(day_dir / stamp, snapshot)
    write_json(day_dir / "latest.json", snapshot)


def build_snapshot() -> dict[str, Any]:
    generated_at = now_utc().isoformat()

    raw_crons = load_crons()
    crons = [normalize_cron(job) for job in raw_crons]
    crons_by_name = {cron["name"]: cron for cron in crons}
    recent_events = recent_event_rows(limit=400)
    workflow_ledger = sync_workflow_ledgers(WORKFLOW_LEDGER_EXPECTATIONS, raw_crons, recent_events)
    workflow_truth = reconcile_from_ledgers(WORKFLOW_LEDGER_EXPECTATIONS)

    sessions = load_sessions(active_minutes=180)
    active_now = load_active_sessions(sessions)

    integrations = build_integrations(crons_by_name)

    domains = [
        build_routines_domain(),
        build_todo_domain(),
        build_digest_domain(crons_by_name),
        {
            "id": "workflow_truth",
            "name": "Delivery Truth",
            "status": workflow_truth.get("status", "healthy").replace("healthy", "ok").replace("degraded", "warning").replace("lying-risk", "error").replace("broken", "error"),
            "kpis": {
                "healthy": workflow_truth.get("counts", {}).get("healthy", 0),
                "degraded": workflow_truth.get("counts", {}).get("degraded", 0),
                "lyingRisk": workflow_truth.get("counts", {}).get("lying-risk", 0),
                "broken": workflow_truth.get("counts", {}).get("broken", 0),
                "timeline": len((workflow_truth.get("history") or {}).get("timeline", [])),
            },
            "pipelines": workflow_truth.get("pipelines", []),
            "timeline": (workflow_truth.get("history") or {}).get("timeline", []),
            "actions": [],
            "source": str((ROOT / "mission-control" / "data" / "workflow-ledger")),
        },
        build_crons_domain(crons),
        build_knowledge_domain(crons_by_name, integrations),
        build_finance_domain(integrations),
        build_therapy_domain(),
        build_security_domain(),
        build_ops_domain(crons_by_name),
    ]

    attach_trends(domains)

    security_domain = next((d for d in domains if d.get("id") == "security"), {"alerts": []})
    action_required = build_action_required(crons, security_domain)

    pending_controls = read_json(QUEUE_FILE, [])
    results = load_recent_control_results(limit=80)

    health_score = score_health(action_required, domains)
    slo = compute_slo(crons, results, domains)

    return {
        "meta": {
            "schemaVersion": "3.1.0",
            "generatorVersion": "2026-03-20.1",
            "generatedAt": generated_at,
        },
        "overview": {
            "healthScore": health_score,
            "criticalAlerts": len([a for a in action_required if a.get("priority") == "high"]),
            "pendingControls": len(pending_controls),
            "dataFreshnessSec": 0,
        },
        "actionRequired": action_required,
        "activeNow": active_now,
        "domains": domains,
        "integrations": integrations,
        "workflowTruth": workflow_truth,
        "workflowLedger": workflow_ledger,
        "security": next((d for d in domains if d.get("id") == "security"), {}),
        "slo": slo,
        "controls": build_controls_catalog(),
        "audit": {
            "queue": pending_controls,
            "recentResults": results,
        },
        "recentActivity": load_today_events(limit=40),
        "products": [
            {
                "name": "Mission Control",
                "url": MISSION_CONTROL_URL,
                "status": "live",
                "lastChecked": generated_at,
            }
        ],
        "crons": crons,
        "lastUpdated": generated_at,
    }


def convert_to_v2(v3: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": {
            "schemaVersion": "2.1.0",
            "generatorVersion": v3.get("meta", {}).get("generatorVersion"),
            "generatedAt": v3.get("meta", {}).get("generatedAt"),
        },
        "overview": v3.get("overview", {}),
        "actionRequired": v3.get("actionRequired", []),
        "activeNow": v3.get("activeNow", []),
        "domains": [d for d in v3.get("domains", []) if d.get("id") != "security"],
        "controls": v3.get("controls", []),
        "audit": v3.get("audit", {}),
        "recentActivity": v3.get("recentActivity", []),
        "products": v3.get("products", []),
        "crons": v3.get("crons", []),
        "lastUpdated": v3.get("lastUpdated"),
    }


def convert_to_legacy(v3: dict[str, Any]) -> dict[str, Any]:
    return {
        "lastUpdated": v3.get("meta", {}).get("generatedAt"),
        "actionRequired": [
            {
                "title": item.get("title"),
                "url": None,
                "priority": item.get("priority", "medium"),
            }
            for item in v3.get("actionRequired", [])
        ],
        "activeNow": [
            {
                "task": item.get("task"),
                "model": item.get("model"),
                "startedAt": item.get("startedAt"),
            }
            for item in v3.get("activeNow", [])
        ],
        "products": v3.get("products", []),
        "crons": [
            {
                "name": row.get("name"),
                "schedule": row.get("schedule"),
                "lastRun": row.get("lastRun"),
                "status": row.get("status"),
                "errors": row.get("errors", 0),
                "lastError": row.get("lastError"),
            }
            for row in v3.get("crons", [])
        ],
        "recentActivity": v3.get("recentActivity", []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Mission Control dashboard snapshot")
    parser.add_argument("--output", type=Path, default=DEFAULT_V3_OUTPUT, help="Path for v3 JSON output")
    parser.add_argument("--v2-output", type=Path, default=V2_OUTPUT, help="Path for v2 JSON output")
    parser.add_argument("--legacy-output", type=Path, default=LEGACY_OUTPUT, help="Path for legacy JSON output")
    parser.add_argument("--no-history", action="store_true", help="Do not persist history snapshot")
    parser.add_argument("--no-legacy", action="store_true", help="Do not write legacy output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    v3 = build_snapshot()

    write_json(args.output, v3)
    write_json(args.v2_output, convert_to_v2(v3))
    if not args.no_legacy:
        write_json(args.legacy_output, convert_to_legacy(v3))
    if not args.no_history:
        persist_history(v3)

    print(f"Wrote {args.output}")
    print(f"Wrote {args.v2_output}")
    if not args.no_legacy:
        print(f"Wrote {args.legacy_output}")
    if not args.no_history:
        print("History persisted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
