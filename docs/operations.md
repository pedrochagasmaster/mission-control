# Mission Control Operations

## 1) Gerar snapshot v3
```bash
cd /home/pedro/.openclaw/workspace
python3 mission-control/scripts/build_dashboard_snapshot.py
```

## 2) Subir API local de controle (token obrigatório recomendado)
```bash
cd /home/pedro/.openclaw/workspace
MC_CONTROL_TOKEN='troque-este-token' \
python3 mission-control/scripts/control_api.py --host 127.0.0.1 --port 18791
```

## 3) Enfileirar comando manual
```bash
cd /home/pedro/.openclaw/workspace
python3 mission-control/scripts/control_queue.py enqueue \
  --action cron.retry \
  --payload jobId=4fe4f71e-f653-4382-95c4-bceb7f7a2e49 \
  --requested-by dashboard
```

## 4) Processar fila
```bash
cd /home/pedro/.openclaw/workspace
python3 mission-control/scripts/control_queue.py process --max-items 20
```

## 5) Listar fila pendente
```bash
python3 mission-control/scripts/control_queue.py list
```

## 6) Fluxo recomendado no cron
1. Rodar `control_queue.py process`
2. Rodar `build_dashboard_snapshot.py`
3. Commit/push no repo `mission-control`

Isso garante que o snapshot reflita o resultado das ações operacionais recentes.
