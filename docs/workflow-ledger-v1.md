# Workflow Ledger V1 — Delivery Truth First

Data: 2026-03-19
Status: V1 implementado (aditivo)

## Objetivo
Parar de tratar `lastStatus=ok` como verdade suficiente.

A V1 introduz uma camada de **workflow truth** no Mission Control para responder:
- o pipeline executou?
- entregou no canal certo?
- caiu em fallback?
- está "mentindo" dizendo que rodou bem quando a entrega falhou?

## Não objetivos
- substituir flows atuais;
- reescrever crons;
- tornar Mission Control fonte primária;
- fazer reconciler mutável em tempo real.

## Modelo mental
A unidade canônica é o **workflow/pipeline**, não o cron isolado.

Cada workflow agrega 1..N jobs e recebe um status canônico:
- `healthy`
- `degraded`
- `lying-risk`
- `broken`

## Workflows tier-1
V1 cobre:
1. `digest`
2. `pluggy`
3. `reminders`
4. `routines`
5. `proactive_group`
6. `tracking_watchdog`
7. `mission_control`

## Regras do reconciler V1

### broken
Quando qualquer job do workflow está em erro estrutural.
Exemplos:
- `lastStatus=error`
- `consecutiveErrors > 0`

### lying-risk
Quando o job parece ter rodado, mas a verdade de entrega contradiz isso.
Exemplos:
- `lastStatus=ok` + `lastDeliveryStatus=not-delivered`
- `lastDelivered=false`

### degraded
Quando o pipeline funciona, mas fora do alvo canônico.
Exemplos:
- fallback por Telegram onde o sucesso pleno esperado é WhatsApp
- evidência incompleta de entrega num workflow com entrega obrigatória

### healthy
Execução e entrega alinhadas com o canal canônico.

## Decisões travadas nesta V1
- **Telegram fallback conta como sucesso degradado**, nunca sucesso pleno.
- **Não existe distinção entregue vs visto** nesta V1.
- **Mission Control é consumidor do ledger**, não fonte primária.
- **Rollout é 100% aditivo**.

## Implementação concreta

### Dados novos no snapshot v3
`dashboard-data.v3.json` agora inclui:
- `workflowTruth.status`
- `workflowTruth.counts`
- `workflowTruth.pipelines[]`

Cada pipeline expõe:
- `id`
- `name`
- `status`
- `confidence`
- `canonicalChannel`
- `deliveryRequired`
- `jobs[]`
- `signals.eventCount`
- `signals.lastEvent`
- `reasons[]`

### UI
Mission Control ganhou uma seção **Workflow Truth** para exibir os tier-1 pipelines com:
- status canônico
- confidence
- canal canônico
- razões do reconciler

## Fontes usadas na V1
- `openclaw cron list` / `jobs.json`
- `memory/events/*.jsonl`
- metadata de entrega dos jobs (`lastDelivered`, `lastDeliveryStatus`)

## Limitações conhecidas
- ainda não existe event store dedicado por attempt;
- reconciler é observacional em batelada, não streaming;
- "fallback usado deliberadamente" ainda não é separado de "degradação incidental";
- disconnect 503 do WhatsApp ainda entra só indiretamente via sinais de entrega.

## Próximo passo natural (V2)
1. criar ledger JSONL dedicado por workflow attempt;
2. registrar eventos explícitos (`triggered`, `ran`, `delivery_ok`, `delivery_failed`, `fallback_used`);
3. separar status do pipeline de status do cron;
4. mostrar timeline por workflow e score de confiança histórico.
