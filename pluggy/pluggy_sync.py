#!/usr/bin/env python3
"""
Sync Pluggy.ai transactions with Tracking Despesas system.
"""
import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from pluggy_client import PluggyClient

# Setup logging
PLUGGY_DIR = Path.home() / '.openclaw' / 'workspace' / 'pluggy'
LOGS_DIR = PLUGGY_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'sync.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('pluggy_sync')

# Pluggy can surface or revise transactions after their booking date. Keep
# overlap in every sync run so late arrivals are still ingested.
MIN_LOOKBACK_DAYS = 7

# Category mapping from Pluggy to tracking categories
CATEGORY_MAP = {
    # Food
    'food': 'Alimentação',
    'food and drinks': 'Alimentação',
    'groceries': 'Alimentação',
    'restaurant': 'Alimentação',
    'eating out': 'Alimentação',
    # Transport
    'transport': 'Transporte',
    'taxi': 'Transporte',
    'uber': 'Transporte',
    'fuel': 'Transporte',
    'gas stations': 'Transporte',
    # Health
    'health': 'Farmácia',
    'pharmacy': 'Farmácia',
    'medical': 'Farmácia',
    # Home/utility
    'utilities': 'Moradia',
    'rent': 'Moradia',
    # Shopping/general
    'shopping': 'Shopping',
    'electronics': 'Shopping',
    # Services/subscriptions
    'services': 'Assinaturas Mensais',
    'digital services': 'Assinaturas Mensais',
    # Transfers/finance
    'transfer': 'Outros',
    'transfers': 'Outros',
    'tax on financial operations': 'Outros',
    # Fallback
    'other': 'Outros',
}


def get_tracking_endpoint():
    """Get tracking API base URL."""
    try:
        result = subprocess.run(
            ['/home/pedro/my_project_dir/tracking_despesas/scripts/app_endpoint.py',
             '--mode', 'status'],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        return data.get('agent_connection', {}).get('api_base_url_local', 'http://127.0.0.1:8000')
    except Exception as e:
        logger.warning(f"Could not get tracking endpoint: {e}, using default")
        return 'http://127.0.0.1:8000'


def ingest_inbox_entries(entries):
    """Send transactions to inbox ingestion endpoint."""
    if not entries:
        return 0

    endpoint = get_tracking_endpoint()
    url = f"{endpoint}/api/inbox/ingest"
    payload = {"entries": entries}

    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in (200, 201):
                body = json.loads(response.read().decode())
                inserted = int(body.get('inserted', 0))
                updated = int(body.get('updated', 0))
                excluded = int(body.get('auto_excluded', 0))
                logger.info(
                    f"✓ Inbox ingest: +{inserted} novos, {updated} atualizados, {excluded} auto-excluídos"
                )
                return inserted + updated
            else:
                logger.error(f"✗ Erro HTTP {response.status}")
                return 0
                
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode()
        except Exception:
            pass
        logger.error(f"✗ Erro HTTP {e.code}: {e.reason}")
        if body:
            logger.error(f"Detalhes: {body}")
        return 0
    except Exception as e:
        logger.error(f"✗ Erro: {type(e).__name__}: {e}")
        return 0


def map_category(pluggy_category: str) -> str:
    """Map Pluggy category to tracking category."""
    if not pluggy_category:
        return 'Outros'
    
    cat_lower = pluggy_category.lower()
    if cat_lower in CATEGORY_MAP:
        return CATEGORY_MAP[cat_lower]

    for key, value in CATEGORY_MAP.items():
        if key in cat_lower:
            return value

    return 'Outros'


def sync_transactions(
    item_id: str = None,
    days: int = 7,
    dry_run: bool = False
):
    """Sync transactions from Pluggy to tracking inbox."""
    effective_days = max(int(days), MIN_LOOKBACK_DAYS)
    if effective_days != days:
        logger.info(
            "Janela solicitada de %s dia(s) ampliada para %s dia(s) para cobrir transações atrasadas",
            days,
            effective_days,
        )
    logger.info(f"=== Iniciando sync Pluggy -> Inbox ({effective_days} dias) ===")

    # Summary stats for JSON output
    summary = {
        "success": False,
        "total_transactions": 0,
        "total_amount": 0.0,
        "expenses_count": 0,
        "expenses_amount": 0.0,
        "income_count": 0,
        "income_amount": 0.0,
        "items_processed": 0,
        "accounts_processed": 0,
        "errors": []
    }

    try:
        client = PluggyClient()
    except FileNotFoundError as e:
        logger.error(f"✗ {e}")
        summary["errors"].append(str(e))
        print(json.dumps(summary, ensure_ascii=False))
        return summary

    # Get items to sync
    if item_id:
        items = [client.get_item(item_id)]
    else:
        tracked_ids = client.get_tracked_items()
        if not tracked_ids:
            logger.warning(
                "Nenhum item trackeado. Use: python3 pluggy_client.py --track-item ITEM_ID"
            )
            summary["errors"].append("Nenhum item trackeado")
            print(json.dumps(summary, ensure_ascii=False))
            return summary
        items = [client.get_item(i) for i in tracked_ids]
        items = [i for i in items if i]

    if not items:
        logger.warning("Nenhum item encontrado para sincronizar")
        summary["errors"].append("Nenhum item encontrado")
        print(json.dumps(summary, ensure_ascii=False))
        return summary

    logger.info(f"Sincronizando {len(items)} item(s)")
    summary["items_processed"] = len(items)

    total_synced = 0
    start_date = (datetime.now() - timedelta(days=effective_days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    for item in items:
        item_id = item.get('id')
        item_status = item.get('status')
        
        if item_status != 'UPDATED':
            logger.warning(f"Item {item_id[:8]} não está atualizado (status: {item_status}), pulando...")
            continue
        
        connector_name = item.get('connector', {}).get('name', 'Desconhecido')
        logger.info(f"Processando: {connector_name}")
        
        # Get accounts for this item
        accounts = client.list_accounts(item_id)
        
        for account in accounts:
            account_id = account.get('id')
            account_name = account.get('name', 'Conta')
            account_type = account.get('type', 'Unknown')
            account_entries = []
            
            logger.info(f"  Conta: {account_name} ({account_type})")
            
            # Get transactions
            transactions = client.list_transactions(
                account_id,
                start_date=start_date,
                end_date=end_date
            )
            
            for tx in transactions:
                try:
                    tx_id = tx.get('id')
                    tx_date = tx.get('date', end_date)
                    tx_amount = tx.get('amount', 0)
                    tx_description = tx.get('description', 'Transação')
                    tx_category = tx.get('category', 'other')
                    tx_type = tx.get('type', 'DEBIT')  # DEBIT or CREDIT

                    # Infer direction to let inbox review and filters handle edge-cases.
                    direction = 'expense'
                    if account_type == 'BANK':
                        direction = 'expense' if ((tx_type == 'DEBIT') or (tx_amount < 0)) else 'income'
                    elif account_type == 'CREDIT':
                        direction = 'expense' if ((tx_type == 'DEBIT') and (tx_amount > 0)) else 'income'
                    else:
                        direction = 'expense' if ((tx_type == 'DEBIT') or (tx_amount < 0)) else 'income'

                    # Track amounts for summary
                    abs_amount = abs(float(tx_amount))
                    if direction == 'expense':
                        summary["expenses_count"] += 1
                        summary["expenses_amount"] += abs_amount
                    else:
                        summary["income_count"] += 1
                        summary["income_amount"] += abs_amount
                    summary["total_transactions"] += 1
                    summary["total_amount"] += abs_amount

                    # Map category: expenses can be prefilled, incomes stay uncategorized for inbox triage.
                    category = map_category(tx_category) if direction == 'expense' else None

                    # Format description
                    description = f"[{connector_name}] {tx_description}"[:200]
                    
                    if dry_run:
                        logger.info(
                            f"    [DRY-RUN] {direction.upper()} | R$ {abs(tx_amount):.2f} | {category or 'sem categoria'} | {description[:50]}"
                        )
                        total_synced += 1
                    else:
                        payload = {
                            "provider": "pluggy",
                            "external_id": str(tx_id),
                            "tx_date": str(tx_date),
                            "amount": abs(float(tx_amount)),
                            "signed_amount": float(tx_amount),
                            "direction": direction,
                            "description": f"{description} [pluggy]",
                            "category": category,
                            "raw_category": tx_category,
                            "account_type": account_type,
                            "tx_type": tx_type,
                            "currency_code": tx.get('currencyCode') or 'BRL',
                        }
                        account_entries.append(payload)
                
                except Exception as e:
                    logger.error(f"    Erro processando transação: {type(e).__name__}: {e}")
                    continue

            if not dry_run and account_entries:
                ingested = ingest_inbox_entries(account_entries)
                if ingested > 0:
                    total_synced += ingested
                else:
                    logger.error(f"    Falha ao enviar lote da conta {account_name} para inbox")

        summary["accounts_processed"] += len(accounts)

    summary["success"] = total_synced > 0 or summary["total_transactions"] == 0
    logger.info(f"=== Sync finalizado: {total_synced} transações enviadas para inbox ===")
    logger.info(f"=== Resumo: {summary['total_transactions']} transações, "
                f"R$ {summary['expenses_amount']:.2f} em despesas, "
                f"R$ {summary['income_amount']:.2f} em receitas ===")

    # Print JSON summary for programmatic consumption
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main():
    parser = argparse.ArgumentParser(description='Sync Pluggy with Tracking')
    parser.add_argument('--item', type=str, help='Specific item ID to sync')
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help=f'Days of history (minimum overlap enforced: {MIN_LOOKBACK_DAYS})',
    )
    parser.add_argument('--dry-run', action='store_true', help='Do not register, just show')

    args = parser.parse_args()

    summary = sync_transactions(
        item_id=args.item,
        days=args.days,
        dry_run=args.dry_run
    )

    sys.exit(0 if summary.get("success") else 1)


if __name__ == '__main__':
    main()
