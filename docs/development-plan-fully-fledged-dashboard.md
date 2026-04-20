# Mission Control - Plano de Desenvolvimento para Dashboard Completo

Data: 2026-03-06
Base funcional: INVENTARIO_FUNCIONALIDADES.md (2026-03-06)

## 1) Objetivo do produto
Levar o Mission Control de um painel operacional (snapshot + ações básicas) para um dashboard completo da Nina, com três camadas:
1. Observabilidade em tempo real por domínio.
2. Operação segura (ações com auditoria e guardrails).
3. Gestão (tendências, qualidade, risco e planejamento).

## 2) Estado atual (baseline real)
1. Snapshot v2 já existe com 8 domínios e fila de controle funcional.
2. UI atual é majoritariamente operacional e orientada a listas/tabelas.
3. Há ações críticas já prontas (`cron.retry`, `cron.pause`, `cron.resume`, `task.mark_done`, `digest.retry_send`).
4. Lacunas: pouca visão histórica, pouca inteligência por domínio, sem trilhas de governança visíveis, sem hardening explícito no painel.

## 3) Princípios de implementação
1. Fonte da verdade continua local (arquivos + `openclaw` CLI + ledger).
2. Nada de expor conteúdo sensível (especialmente terapia).
3. Toda ação mutável precisa de confirmação, auditoria e resultado rastreável.
4. Entrega incremental por fases, sem big bang.

## 4) Roadmap por fases

## Fase 0 - Foundation Hardening (2-3 dias)
Objetivo: estabilizar o que já existe para não construir em cima de base frágil.

Entregáveis:
1. Criar `mission-control/docs/control-actions-contract.md` com payloads, validações e erros esperados.
2. Adicionar validação de schema no build (`dashboard-data.v2.json`) com falha explícita no CI/cron.
3. Incluir checagens de integridade no snapshot (arquivos ausentes, JSON inválido, campos nulos críticos).
4. Normalizar timezone em todos os jobs com `tzMissing` (visível e rastreável no painel).
5. Garantir rotação e limite de `control-results.jsonl` (evitar crescimento infinito).

Critério de pronto:
1. Health score deixa de oscilar por erro estrutural e passa a refletir só problemas reais de operação.

## Fase 1 - Control Plane v1 (4-5 dias)
Objetivo: tornar o dashboard realmente acionável sem depender de copiar comando manual.

Entregáveis:
1. Criar endpoint local de enqueue (ex.: `mission-control/scripts/control_api.py`) com token simples local.
2. UI passa a enfileirar direto via API e mostrar status imediato do comando.
3. Adicionar ações novas no `control_queue.py`:
1. `cron.set_timezone`
2. `cron.run_all_failed`
3. `task.mark_skipped`
4. `todo.set_deadline`
4. Confirm modal para ações destrutivas (`cron.pause`).
5. Trilha de auditoria no UI com filtros por ação, resultado e período.

Critério de pronto:
1. 90%+ das operações recorrentes do Pedro executadas sem terminal.

## Fase 2 - Domain Dashboards (1 semana)
Objetivo: dar profundidade por domínio (não só KPI agregado).

Entregáveis por domínio:
1. Rotinas:
1. Heatmap semanal de pendências por horário.
2. Taxa de conclusão por rotina (7/30 dias).
3. Indicação de atraso real vs atraso esperado.
2. To-do + Deadlines:
1. Kanban simples (`PENDING`, `DONE`, `SKIPPED`).
2. Priorização por urgência (hoje, 3 dias, atrasado).
3. Diário da Família:
1. Pipeline visual (gerador -> enviador -> watchdogs).
2. SLA de envio (enviado até 07:50).
3. Causas raiz de falhas de envio por categoria.
4. Knowledge:
1. Saúde de ingest (sucesso/falha por fonte).
2. Novos conteúdos por dia.
3. Latência entre ingest e impacto no digest.
5. Finanças:
1. Status Pluggy e último sync.
2. Indicador de cobertura (contas sincronizadas vs esperadas).
3. Placeholder estruturado para Open Banking (status planejado).
6. Terapia (privado, sem conteúdo):
1. Somente metadados (arquivos, última atualização, permissões).
2. Alerta de permissões inseguras.
7. Ops:
1. Estado de jobs críticos.
2. Eventos por hora.
3. Tendência de incidentes.

Critério de pronto:
1. Cada domínio com visão de status atual + tendência + ação recomendada.

## Fase 3 - Governance & Privacy Center (4-5 dias)
Objetivo: explicitar regras de canal e privacidade dentro do dashboard.

Entregáveis:
1. Card de compliance por canal:
1. Chat da Nina: somente digest + respostas diretas.
2. Rotinas/cobradores: fora do grupo.
3. Terapia: nunca em grupo.
2. Detector de risco configuracional:
1. Jobs potencialmente violando política de canal.
2. Ações bloqueadas automaticamente (com explicação).
3. Painel de permissões:
1. `memory/therapy/*.md` esperado 600.
2. `~/.openclaw/credentials` esperado 700.

Critério de pronto:
1. Dashboard passa a prevenir regressão de privacidade, não só observar.

## Fase 4 - Reliability & Incident Module (1 semana)
Objetivo: transformar incidentes em rotina tratável.

Entregáveis:
1. Timeline de incidentes por tipo (gateway, delivery, cron, parse, credencial).
2. Runbook assistido por incidente (botões com comandos seguros pré-preenchidos).
3. Pós-mortem leve no painel:
1. impacto
2. duração
3. causa provável
4. ação preventiva
4. Alertas com severidade e deduplicação.
5. SLOs operacionais:
1. sucesso do digest diário
2. sucesso dos crons críticos
3. tempo de recuperação

Critério de pronto:
1. Incidente deixa de ser caça manual e vira fluxo em 3 passos: detectar, agir, validar.

## Fase 5 - Strategic Layer (4-5 dias)
Objetivo: sair de operação diária para gestão da evolução da Nina.

Entregáveis:
1. Scorecard semanal por domínio (0-100) com explicabilidade.
2. Tendência 30 dias (melhora/piora) por:
1. rotina
2. digest
3. ingest knowledge
4. confiabilidade financeira
3. Mapa de backlog embutido no dashboard com status (`todo`, `doing`, `done`).
4. Bloco de recomendações automáticas com impacto estimado.

Critério de pronto:
1. O painel responde claramente: "onde investir esforço esta semana?"

## 5) Backlog técnico transversal
1. Migrar JS inline para módulos (`mission-control/web/`) para manutenção.
2. Separar camada de dados (collector) da camada de apresentação (UI).
3. Criar testes automatizados:
1. unit para builders de domínio
2. contract test do schema
3. smoke test de ações de controle
4. Adicionar snapshot history (`mission-control/data/history/YYYY-MM-DD/*.json`) para gráficos reais.
5. Adicionar feature flags por módulo no dashboard.

## 6) Métricas de sucesso (KPIs de produto)
1. Operação:
1. 95%+ ações feitas via dashboard (não terminal).
2. 0 ações sem audit trail.
2. Confiabilidade:
1. Digest enviado até 07:50 em >= 95% dos dias.
2. MTTR de incidentes críticos < 30 min.
3. Governança:
1. 0 vazamentos de terapia.
2. 0 envio indevido no Chat da Nina.
4. Qualidade de dados:
1. 0 snapshot inválido em produção.
2. Cobertura de domínios 100% com KPIs e tendência.

## 7) Sequência de execução recomendada
1. Fase 0
2. Fase 1
3. Fase 2
4. Fase 3
5. Fase 4
6. Fase 5

Justificativa: primeiro estabiliza e operacionaliza, depois aprofunda domínio, depois fecha governança e escala para confiabilidade e estratégia.

## 8) Próxima sprint (sprint inicial sugerida - 5 dias)
1. Implementar `cron.set_timezone` no queue processor.
2. Expor enqueue endpoint local com autenticação mínima.
3. Conectar UI para ações diretas (sem copiar comando).
4. Adicionar histórico diário de snapshots.
5. Entregar primeira versão de tendências de rotinas (7 dias).
6. Entregar painel de compliance de canal (somente leitura nesta sprint).

## 9) Definition of Done para "Fully Fledged"
1. Todos os domínios do inventário com:
1. status atual
2. tendência histórica
3. ações de controle relevantes
4. regras de privacidade/governança visíveis
2. Operações críticas executáveis sem terminal.
3. Auditoria completa de qualquer ação feita no dashboard.
4. Hardening mínimo validado continuamente pelo próprio painel.
5. Runbooks de incidentes integrados e utilizáveis em produção.
