# Mission Control Schema v3

## Arquivo principal
- `mission-control/data/dashboard-data.v3.json`

## Compatibilidade
- `mission-control/data/dashboard-data.v2.json` (compat)
- `mission-control/data/dashboard-data.json` (legado)
- `mission-control/data/workflow-ledger/*.jsonl` (ledger V2 derivado por workflow)

## Estrutura v3
- `meta`
- `overview`
- `workflowLedger`
- `workflowTruth`
- `actionRequired[]`
- `activeNow[]`
- `domains[]` (com `trend7d`)
- `integrations`
- `security`
- `slo`
- `controls[]`
- `audit.queue[]`
- `audit.recentResults[]`
- `recentActivity[]`
- `products[]`
- `crons[]`

## Domínios padrão
- `routines`
- `workflow_truth`
- `todo`
- `digest`
- `crons`
- `knowledge`
- `finance`
- `therapy`
- `security`
- `ops`

## Contrato de controle
### Queue (`control-queue.json`)
```json
[
  {
    "commandId": "uuid",
    "createdAt": "ISO-8601",
    "requestedBy": "dashboard|api|cli",
    "status": "queued",
    "action": "cron.retry",
    "payload": {"jobId": "..."}
  }
]
```

### Results (`control-results.jsonl`)
```json
{
  "commandId": "uuid",
  "executedAt": "ISO-8601",
  "executor": "mission-control/scripts/control_queue.py",
  "action": "task.mark_done",
  "payload": {"source": "daily", "taskKey": "rotina_manha"},
  "result": "ok|error",
  "message": "stdout/stderr resumido"
}
```

## Ações suportadas
- `cron.retry`
- `cron.pause`
- `cron.resume`
- `cron.set_timezone`
- `cron.run_all_failed`
- `digest.retry_send`
- `task.mark_done`
- `task.mark_skipped`
- `todo.set_deadline`
