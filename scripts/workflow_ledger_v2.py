#!/usr/bin/env python3
"""Workflow ledger V2 helpers for Mission Control.

Aditivo: gera/atualiza um ledger JSONL por workflow attempt a partir das fontes
primárias já existentes (jobs + memory/events) e oferece um reconciler em
batelada consumindo esse ledger.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "mission-control" / "data" / "workflow-ledger"

EVENT_TRIGGERED = "triggered"
EVENT_RAN = "ran"
EVENT_DELIVERY_OK = "delivery_ok"
EVENT_DELIVERY_FAILED = "delivery_failed"
EVENT_FALLBACK_USED = "fallback_used"
TERMINAL_EVENTS = {EVENT_DELIVERY_OK, EVENT_DELIVERY_FAILED, EVENT_FALLBACK_USED}
EVENT_ORDER = {
    EVENT_TRIGGERED: 1,
    EVENT_RAN: 2,
    EVENT_DELIVERY_OK: 3,
    EVENT_DELIVERY_FAILED: 3,
    EVENT_FALLBACK_USED: 3,
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def iso_from_ms(ms: Any) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).isoformat()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def attempt_id(workflow_id: str, job_id: str, ts: str) -> str:
    parsed = parse_iso(ts)
    if parsed is None:
        stamp = ts.replace(":", "").replace("-", "") if ts else "unknown"
    else:
        stamp = parsed.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M")
    return f"{workflow_id}:{job_id}:{stamp}"


def _base_event(
    workflow_id: str,
    workflow_name: str,
    job: dict[str, Any],
    ts: str,
    event_type: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "workflowId": workflow_id,
        "workflowName": workflow_name,
        "attemptId": attempt_id(workflow_id, str(job.get("id") or "unknown"), ts or "unknown"),
        "jobId": job.get("id"),
        "jobName": job.get("name"),
        "timestamp": ts,
        "eventType": event_type,
        **extra,
    }


def infer_events_for_workflow(
    workflow_id: str,
    spec: dict[str, Any],
    raw_jobs: list[dict[str, Any]],
    recent_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_by_name = {str(job.get("name") or ""): job for job in raw_jobs}
    jobs = [raw_by_name[name] for name in spec.get("jobs", []) if name in raw_by_name]
    job_ids = {str(job.get("id") or "") for job in jobs}
    ledger_events: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def add(event: dict[str, Any]) -> None:
        key = (str(event.get("attemptId")), str(event.get("eventType")), str(event.get("timestamp")))
        if key in seen_keys:
            return
        seen_keys.add(key)
        ledger_events.append(event)

    for row in recent_events:
        chat_id = str(row.get("chat_id") or "")
        matched_job = next((job for job in jobs if str(job.get("id") or "") and str(job.get("id")) in chat_id), None)
        if not matched_job:
            continue
        ts = row.get("timestamp") or row.get("local_timestamp")
        if not ts:
            continue
        add(_base_event(workflow_id, spec["name"], matched_job, ts, EVENT_TRIGGERED, source="memory/events", rawChannel=row.get("channel")))
        add(_base_event(workflow_id, spec["name"], matched_job, ts, EVENT_RAN, source="memory/events", inferred=True))

    expected_channel = spec.get("successChannel")
    fallback_channels = set(spec.get("fallbackChannels") or [])

    for job in jobs:
        state = job.get("state") or {}
        ts = iso_from_ms(state.get("lastRunAtMs"))
        if not ts:
            continue
        add(_base_event(workflow_id, spec["name"], job, ts, EVENT_TRIGGERED, source="cron-state", inferred=True))
        add(
            _base_event(
                workflow_id,
                spec["name"],
                job,
                ts,
                EVENT_RAN,
                source="cron-state",
                runStatus=state.get("lastRunStatus") or state.get("lastStatus"),
                inferred=True,
            )
        )

        delivered = state.get("lastDelivered")
        delivery_status = state.get("lastDeliveryStatus")
        configured_channel = (job.get("delivery") or {}).get("channel")
        effective_channel = configured_channel if configured_channel and configured_channel != "last" else expected_channel

        if delivered is True or delivery_status == "delivered":
            if effective_channel in fallback_channels:
                add(
                    _base_event(
                        workflow_id,
                        spec["name"],
                        job,
                        ts,
                        EVENT_FALLBACK_USED,
                        channel=effective_channel,
                        canonicalChannel=spec.get("canonicalChannel"),
                        deliveryStatus=delivery_status,
                        source="cron-state",
                    )
                )
            else:
                add(
                    _base_event(
                        workflow_id,
                        spec["name"],
                        job,
                        ts,
                        EVENT_DELIVERY_OK,
                        channel=effective_channel,
                        canonicalChannel=spec.get("canonicalChannel"),
                        deliveryStatus=delivery_status,
                        source="cron-state",
                    )
                )
        elif spec.get("deliveryRequired") and (delivery_status == "not-delivered" or delivered is False):
            add(
                _base_event(
                    workflow_id,
                    spec["name"],
                    job,
                    ts,
                    EVENT_DELIVERY_FAILED,
                    channel=effective_channel or configured_channel,
                    canonicalChannel=spec.get("canonicalChannel"),
                    deliveryStatus=delivery_status,
                    source="cron-state",
                )
            )

    ledger_events.sort(key=lambda row: ((row.get("timestamp") or ""), (row.get("attemptId") or ""), EVENT_ORDER.get(str(row.get("eventType")), 99)))
    return ledger_events


def sync_workflow_ledgers(
    expectations: dict[str, dict[str, Any]],
    raw_jobs: list[dict[str, Any]],
    recent_events: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest: dict[str, Any] = {"workflows": {}}
    for workflow_id, spec in expectations.items():
        path = LEDGER_DIR / f"{workflow_id}.jsonl"
        merged = infer_events_for_workflow(workflow_id, spec, raw_jobs, recent_events)
        write_jsonl(path, merged)
        manifest["workflows"][workflow_id] = {
            "path": str(path),
            "events": len(merged),
        }
    return manifest


def _attempt_from_events(spec: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(events, key=lambda row: ((row.get("timestamp") or ""), EVENT_ORDER.get(str(row.get("eventType")), 99)))
    event_types = [row.get("eventType") for row in ordered]
    first_ts = ordered[0].get("timestamp") if ordered else None
    last_ts = ordered[-1].get("timestamp") if ordered else None
    channel = next((row.get("channel") for row in reversed(ordered) if row.get("channel")), None)
    terminal = next((row for row in reversed(ordered) if row.get("eventType") in TERMINAL_EVENTS), None)

    if terminal:
        if terminal.get("eventType") == EVENT_DELIVERY_OK:
            status = "healthy"
            reasons = ["delivery_ok no canal canônico"]
        elif terminal.get("eventType") == EVENT_FALLBACK_USED:
            status = "degraded"
            reasons = [f"fallback usado via {terminal.get('channel') or 'canal-alternativo'}"]
        else:
            status = "lying-risk"
            reasons = ["execução observada sem entrega válida"]
    else:
        if spec.get("deliveryRequired"):
            status = "degraded"
            reasons = ["attempt sem evento terminal de entrega"]
        else:
            status = "healthy" if EVENT_RAN in event_types else "degraded"
            reasons = ["workflow interno sem requisito de entrega"]

    confidence = 100
    if EVENT_TRIGGERED in event_types:
        confidence += 0
    else:
        confidence -= 25
    if EVENT_RAN not in event_types:
        confidence -= 20
    if status == "degraded":
        confidence -= 18
    elif status == "lying-risk":
        confidence -= 35
    confidence = max(20, min(100, confidence))

    return {
        "attemptId": ordered[0].get("attemptId") if ordered else None,
        "jobId": ordered[0].get("jobId") if ordered else None,
        "jobName": ordered[0].get("jobName") if ordered else None,
        "status": status,
        "confidence": confidence,
        "startedAt": first_ts,
        "lastEventAt": last_ts,
        "channel": channel,
        "eventTypes": event_types,
        "eventCount": len(ordered),
        "reasons": reasons,
        "events": ordered,
    }


def reconcile_from_ledgers(expectations: dict[str, dict[str, Any]], recent_attempts_limit: int = 6) -> dict[str, Any]:
    pipelines: list[dict[str, Any]] = []
    counts = {"healthy": 0, "degraded": 0, "lying-risk": 0, "broken": 0}
    global_timeline: list[dict[str, Any]] = []

    for workflow_id, spec in expectations.items():
        rows = read_jsonl(LEDGER_DIR / f"{workflow_id}.jsonl")
        attempts_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            attempts_map[str(row.get("attemptId") or "unknown")].append(row)

        attempts = [_attempt_from_events(spec, evs) for _, evs in attempts_map.items()]
        attempts.sort(key=lambda row: row.get("startedAt") or "")
        recent_attempts = attempts[-recent_attempts_limit:]
        latest_attempt = recent_attempts[-1] if recent_attempts else None

        history_counts = Counter(attempt.get("status") for attempt in attempts)
        history_by_day: dict[str, Counter[str]] = defaultdict(Counter)
        for attempt in attempts:
            started = attempt.get("startedAt")
            day = str(started)[:10] if started else "unknown"
            history_by_day[day][str(attempt.get("status") or "unknown")] += 1
            global_timeline.append({
                "workflowId": workflow_id,
                "workflowName": spec["name"],
                "attemptId": attempt.get("attemptId"),
                "status": attempt.get("status"),
                "startedAt": attempt.get("startedAt"),
                "lastEventAt": attempt.get("lastEventAt"),
                "jobName": attempt.get("jobName"),
                "channel": attempt.get("channel"),
                "eventTypes": attempt.get("eventTypes", []),
                "reasons": attempt.get("reasons", []),
            })

        if latest_attempt:
            pipeline_status = latest_attempt["status"]
            confidence = latest_attempt["confidence"]
            reasons = latest_attempt["reasons"]
        elif spec.get("jobs"):
            pipeline_status = "broken"
            confidence = 15
            reasons = ["sem attempts no ledger ainda"]
        else:
            pipeline_status = "broken"
            confidence = 15
            reasons = ["sem jobs mapeados"]

        counts[pipeline_status] += 1
        pipelines.append({
            "id": workflow_id,
            "name": spec["name"],
            "status": pipeline_status,
            "confidence": confidence,
            "canonicalChannel": spec.get("canonicalChannel"),
            "deliveryRequired": bool(spec.get("deliveryRequired")),
            "signals": {
                "eventCount": len(rows),
                "attemptCount": len(attempts),
                "lastEvent": latest_attempt.get("lastEventAt") if latest_attempt else None,
                "lastAttemptStatus": latest_attempt.get("status") if latest_attempt else None,
            },
            "history": {
                "attemptsTotal": len(attempts),
                "healthy": history_counts.get("healthy", 0),
                "degraded": history_counts.get("degraded", 0),
                "lyingRisk": history_counts.get("lying-risk", 0),
                "broken": history_counts.get("broken", 0),
                "byDay": [
                    {
                        "date": day,
                        "healthy": counter.get("healthy", 0),
                        "degraded": counter.get("degraded", 0),
                        "lyingRisk": counter.get("lying-risk", 0),
                        "broken": counter.get("broken", 0),
                    }
                    for day, counter in sorted(history_by_day.items())[-14:]
                ],
            },
            "recentAttempts": recent_attempts,
            "reasons": reasons,
        })

    overall = "healthy"
    if counts["broken"]:
        overall = "broken"
    elif counts["lying-risk"]:
        overall = "lying-risk"
    elif counts["degraded"]:
        overall = "degraded"

    global_timeline.sort(key=lambda row: row.get("startedAt") or "")
    return {
        "status": overall,
        "counts": counts,
        "pipelines": pipelines,
        "history": {
            "timeline": global_timeline[-30:],
        },
        "ledger": {
            "version": "2.0.0",
            "dir": str(LEDGER_DIR),
        },
    }
