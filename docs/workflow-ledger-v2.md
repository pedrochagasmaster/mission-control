# Workflow Ledger V2 — Attempts explícitos + reconciler por ledger

Data: 2026-03-20
Status: V2 implementado de forma aditiva

## O que muda
A V2 adiciona um **ledger JSONL por workflow** em `mission-control/data/workflow-ledger/*.jsonl`.

A unidade canônica agora é o **workflow attempt**. Cada attempt agrega eventos explícitos:
- `triggered`
- `ran`
- `delivery_ok`
- `delivery_failed`
- `fallback_used`

## Regras travadas
- Mission Control continua **consumidor**, não fonte primária.
- O ledger V2 é **derivado** de fontes já existentes (`jobs.json` + `memory/events/*.jsonl` + estado atual do cron).
- Rollout continua **aditivo**: flows antigos não são alterados.
- **Telegram fallback continua degradado**, nunca sucesso pleno.

## Layout do ledger
Um evento JSONL contém, no mínimo:
- `workflowId`
- `workflowName`
- `attemptId`
- `jobId`
- `jobName`
- `timestamp`
- `eventType`

Campos extras opcionais:
- `channel`
- `canonicalChannel`
- `deliveryStatus`
- `runStatus`
- `source`
- `inferred`

## Reconciler em batelada
O snapshot builder agora faz duas etapas:
1. `sync_workflow_ledgers(...)` — materializa/atualiza os ledgers V2
2. `reconcile_from_ledgers(...)` — lê apenas o ledger e produz `workflowTruth`

Ou seja: o Mission Control deixou de inferir a verdade do workflow direto do estado cru a cada pipeline; ele reconcilia a partir do ledger V2.

## Status por attempt
- `healthy` → terminal `delivery_ok`
- `degraded` → terminal `fallback_used` ou attempt sem entrega terminal quando há evidência incompleta
- `lying-risk` → terminal `delivery_failed` depois de execução observada
- `broken` → ausência total de attempts no ledger para um workflow mapeado

## Snapshot v3
`dashboard-data.v3.json` agora expõe:
- `workflowLedger` (manifest do sync)
- `workflowTruth.ledger`
- `workflowTruth.history.timeline[]`
- `workflowTruth.pipelines[].history`
- `workflowTruth.pipelines[].recentAttempts[]`

## UI mínima entregue
Mission Control agora mostra:
- contadores históricos por workflow
- último attempt / status mais recente
- lista de attempts recentes com timeline curta (`eventTypes`)

## Limites conhecidos
- Como o ledger é derivado, histórico profundo depende da retenção das fontes atuais.
- Eventos `delivery_ok`/`fallback_used` históricos só existem onde a evidência está disponível no estado do cron no momento do sync.
- Ainda não há writer primário embutido no runtime do cron; isso ficaria para uma V3 runtime-first.
