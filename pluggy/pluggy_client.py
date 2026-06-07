#!/usr/bin/env python3
"""
Pluggy.ai Client - Open Banking Integration
Docs: https://docs.pluggy.ai/

This client handles:
- Authentication (OAuth2 Client Credentials)
- Item creation and connection
- Transaction fetching
- Webhook handling
- Sync with local tracking system
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error
import ssl

# Config paths
PLUGGY_DIR = Path.home() / '.openclaw' / 'workspace' / 'pluggy'
CREDENTIALS_DIR = PLUGGY_DIR / 'credentials'
TOKENS_DIR = PLUGGY_DIR / 'tokens'
LOGS_DIR = PLUGGY_DIR / 'logs'
TRACKED_ITEMS_FILE = PLUGGY_DIR / 'tracked_items.json'

# Setup logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'pluggy.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('pluggy')

# API URLs
API_URL = 'https://api.pluggy.ai'
# Current Pluggy auth endpoint is POST /auth.
# Keep a fallback for older implementations that used /auth/api-key.
AUTH_URLS = [f'{API_URL}/auth', f'{API_URL}/auth/api-key']


class PluggyClient:
    """Client for Pluggy.ai Open Banking API."""
    
    def __init__(self):
        self.client_id = self._load_credential('client_id')
        self.client_secret = self._load_credential('client_secret')
        self.api_key = None
        self.api_key_expires_at = None
        
        # Load existing API key if available
        self._load_api_key()
    
    def _load_credential(self, name: str) -> str:
        """Load credential from file."""
        cred_file = CREDENTIALS_DIR / f"{name}.txt"
        if not cred_file.exists():
            raise FileNotFoundError(f"Credencial não encontrada: {cred_file}")
        return cred_file.read_text().strip()
    
    def _load_api_key(self):
        """Load existing API key from file."""
        token_file = TOKENS_DIR / 'api_key.json'
        if token_file.exists():
            with open(token_file) as f:
                data = json.load(f)
                self.api_key = data.get('api_key')
                self.api_key_expires_at = data.get('expires_at')

    def _load_tracked_items(self) -> List[str]:
        """Load locally tracked item IDs."""
        if not TRACKED_ITEMS_FILE.exists():
            return []
        try:
            data = json.loads(TRACKED_ITEMS_FILE.read_text())
            item_ids = data.get('item_ids', [])
            if isinstance(item_ids, list):
                return [str(i).strip() for i in item_ids if str(i).strip()]
            return []
        except Exception as e:
            logger.warning(f"Falha ao ler tracked_items.json: {e}")
            return []

    def _save_tracked_items(self, item_ids: List[str]):
        """Persist locally tracked item IDs."""
        payload = {
            'item_ids': sorted(set(item_ids)),
            'updated_at': datetime.now().isoformat()
        }
        TRACKED_ITEMS_FILE.write_text(json.dumps(payload, indent=2))

    def add_tracked_item(self, item_id: str) -> bool:
        """Add item ID to local tracking file."""
        clean_item_id = item_id.strip()
        if not clean_item_id:
            return False
        item_ids = self._load_tracked_items()
        if clean_item_id in item_ids:
            return True
        item_ids.append(clean_item_id)
        self._save_tracked_items(item_ids)
        logger.info(f"✓ Item adicionado ao tracking local: {clean_item_id}")
        return True

    def remove_tracked_item(self, item_id: str) -> bool:
        """Remove item ID from local tracking file."""
        clean_item_id = item_id.strip()
        item_ids = self._load_tracked_items()
        if clean_item_id not in item_ids:
            return False
        item_ids = [i for i in item_ids if i != clean_item_id]
        self._save_tracked_items(item_ids)
        logger.info(f"✓ Item removido do tracking local: {clean_item_id}")
        return True

    def get_tracked_items(self) -> List[str]:
        """Return locally tracked item IDs."""
        return self._load_tracked_items()
    
    def _save_api_key(self, api_key: str, expires_in: int = 7200):
        """Save API key to file."""
        TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
        with open(TOKENS_DIR / 'api_key.json', 'w') as f:
            json.dump({
                'api_key': api_key,
                'expires_at': expires_at,
                'created_at': datetime.now().isoformat()
            }, f, indent=2)
        self.api_key = api_key
        self.api_key_expires_at = expires_at
    
    def _is_api_key_valid(self) -> bool:
        """Check if current API key is still valid."""
        if not self.api_key or not self.api_key_expires_at:
            return False
        expires = datetime.fromisoformat(self.api_key_expires_at)
        # Considerar inválido se faltar menos de 5 minutos
        return datetime.now() < expires - timedelta(minutes=5)
    
    def authenticate(self) -> bool:
        """
        Authenticate with Pluggy API using client credentials.
        Returns API key on success.
        """
        logger.info("Autenticando com Pluggy.ai...")
        
        data = {
            'clientId': self.client_id,
            'clientSecret': self.client_secret
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        for url in AUTH_URLS:
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode('utf-8'),
                    headers=headers,
                    method='POST'
                )

                with urllib.request.urlopen(req, timeout=30) as response:
                    result = json.loads(response.read().decode())

                    api_key = result.get('apiKey')
                    if not api_key:
                        logger.error("✗ Resposta de autenticação sem apiKey")
                        return False

                    expires_in = result.get('expiresIn', 7200)  # Default 2 hours

                    self._save_api_key(api_key, expires_in)
                    logger.info(f"✓ Autenticado com sucesso (expira em {expires_in}s)")
                    return True

            except urllib.error.HTTPError as e:
                try:
                    error_body = e.read().decode()
                except Exception:
                    error_body = ''

                # /auth/api-key is legacy fallback; if it fails, keep trying.
                if url.endswith('/auth/api-key'):
                    logger.debug(f"Endpoint legado falhou HTTP {e.code}: {error_body}")
                    continue

                logger.error(f"✗ Erro de autenticação HTTP {e.code}: {e.reason}")
                if error_body:
                    logger.error(f"Detalhes: {error_body}")
                return False
            except Exception as e:
                logger.error(f"✗ Erro inesperado: {type(e).__name__}: {e}")
                return False

        return False
    
    def ensure_authenticated(self) -> bool:
        """Ensure we have a valid API key."""
        if self._is_api_key_valid():
            return True
        return self.authenticate()
    
    def _api_request(
        self,
        endpoint: str,
        method: str = 'GET',
        data: dict = None,
        retry_on_401: bool = True
    ) -> Optional[dict]:
        """Make authenticated API request."""
        if not self.ensure_authenticated():
            return None
        
        url = f"{API_URL}{endpoint}"
        
        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        
        try:
            req_data = None
            if data:
                req_data = json.dumps(data).encode('utf-8')
            
            req = urllib.request.Request(
                url,
                data=req_data,
                headers=headers,
                method=method
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
                
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode()
            except Exception:
                error_body = ''

            logger.error(f"✗ API Error {e.code}: {e.reason}")
            if error_body:
                logger.error(f"Detalhes: {error_body}")

            if e.code == 401 and retry_on_401:
                # Retry once after forcing token refresh.
                logger.info("401 recebido, tentando renovar API key uma vez...")
                if self.authenticate():
                    return self._api_request(endpoint, method, data, retry_on_401=False)

                logger.error("Falha ao renovar API key após 401")
            return None
        except Exception as e:
            logger.error(f"✗ Request error: {type(e).__name__}: {e}")
            return None
    
    def list_connectors(self) -> List[Dict]:
        """List all available bank connectors (institutions)."""
        logger.info("Listando conectores disponíveis...")
        result = self._api_request('/connectors')
        if result and 'results' in result:
            connectors = result['results']
            logger.info(f"✓ Encontrados {len(connectors)} conectores")
            return connectors
        return []
    
    def create_item(self, connector_id: str, credentials: Dict, options: Dict = None) -> Optional[Dict]:
        """
        Create a new item (bank connection).
        
        Args:
            connector_id: ID do banco/conector
            credentials: Dict com credenciais do usuário (login, senha, etc)
            options: Opções adicionais
        """
        logger.info(f"Criando item para connector {connector_id}...")
        
        data = {
            'connectorId': connector_id,
            'credentials': credentials
        }
        
        if options:
            data['options'] = options
        
        result = self._api_request('/items', method='POST', data=data)
        
        if result:
            item_id = result.get('id')
            logger.info(f"✓ Item criado: {item_id}")
            return result
        return None
    
    def get_item(self, item_id: str) -> Optional[Dict]:
        """Get item status and details."""
        logger.info(f"Buscando item {item_id[:8]}...")
        return self._api_request(f'/items/{item_id}')
    
    def list_items(self) -> List[Dict]:
        """
        List items is intentionally not exposed by Pluggy API for security reasons.
        Keep compatibility by returning local tracked items with resolved status.
        """
        logger.info("Listagem remota de /items não é suportada; usando tracking local.")
        items = []
        for item_id in self.get_tracked_items():
            item = self.get_item(item_id)
            if item:
                items.append(item)
        logger.info(f"✓ Itens resolvidos via tracking local: {len(items)}")
        return items
    
    def delete_item(self, item_id: str) -> bool:
        """Delete an item (disconnect bank)."""
        logger.info(f"Deletando item {item_id[:8]}...")
        result = self._api_request(f'/items/{item_id}', method='DELETE')
        return result is not None
    
    def list_accounts(self, item_id: str) -> List[Dict]:
        """List all accounts for an item."""
        logger.info(f"Listando contas do item {item_id[:8]}...")
        result = self._api_request(f'/accounts?itemId={item_id}')
        if result and 'results' in result:
            accounts = result['results']
            logger.info(f"✓ Encontradas {len(accounts)} contas")
            return accounts
        return []
    
    def list_transactions(
        self,
        account_id: str,
        start_date: str = None,
        end_date: str = None
    ) -> List[Dict]:
        """
        List transactions for an account.
        
        Args:
            account_id: ID da conta
            start_date: YYYY-MM-DD (default: 30 dias atrás)
            end_date: YYYY-MM-DD (default: hoje)
        """
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        logger.info(f"Buscando transações de {start_date} até {end_date}...")
        
        query = f'?accountId={account_id}&from={start_date}&to={end_date}'
        
        all_transactions = []
        page = 1
        
        while True:
            result = self._api_request(f'/transactions{query}&page={page}')
            
            if not result or 'results' not in result:
                break
            
            transactions = result['results']
            all_transactions.extend(transactions)
            
            # Check if there's more pages
            if not result.get('pageCount') or page >= result['pageCount']:
                break
            
            page += 1
        
        logger.info(f"✓ Encontradas {len(all_transactions)} transações")
        return all_transactions
    
    def get_transaction(self, transaction_id: str) -> Optional[Dict]:
        """Get specific transaction details."""
        return self._api_request(f'/transactions/{transaction_id}')


def main():
    """Test the Pluggy client."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Pluggy.ai Client')
    parser.add_argument('--list-connectors', action='store_true', help='List available connectors')
    parser.add_argument('--list-items', action='store_true', help='List connected items')
    parser.add_argument('--list-tracked', action='store_true', help='List locally tracked item IDs')
    parser.add_argument('--track-item', type=str, help='Track item ID locally for sync')
    parser.add_argument('--untrack-item', type=str, help='Remove tracked item ID')
    
    args = parser.parse_args()
    
    try:
        client = PluggyClient()
        
        if args.track_item:
            if client.add_tracked_item(args.track_item):
                print(f"✓ Item trackeado: {args.track_item}")
            else:
                print("✗ Não foi possível trackear item")

        elif args.untrack_item:
            if client.remove_tracked_item(args.untrack_item):
                print(f"✓ Item removido: {args.untrack_item}")
            else:
                print("✗ Item não encontrado no tracking local")

        elif args.list_tracked or args.list_items:
            item_ids = client.get_tracked_items()
            print(f"\nItems trackeados localmente ({len(item_ids)}):")
            for item_id in item_ids:
                item = client.get_item(item_id)
                if item:
                    status = item.get('status', 'UNKNOWN')
                    connector = item.get('connector', {}).get('name', 'Desconhecido')
                    print(f"  - {item_id} | {connector} | status={status}")
                else:
                    print(f"  - {item_id} | status=INACESSÍVEL")

        elif args.list_connectors:
            connectors = client.list_connectors()
            print(f"\nConectores disponíveis ({len(connectors)}):")
            for conn in connectors[:10]:  # Show first 10
                print(f"  - {conn.get('name')} (ID: {conn.get('id')})")

        else:
            # Just test authentication
            if client.authenticate():
                print("✓ Autenticação com Pluggy.ai bem-sucedida!")
            else:
                print("✗ Falha na autenticação")
    
    except FileNotFoundError as e:
        print(f"✗ Erro: {e}")
        print("\nPara configurar, crie os arquivos:")
        print(f"  {CREDENTIALS_DIR}/client_id.txt")
        print(f"  {CREDENTIALS_DIR}/client_secret.txt")


if __name__ == '__main__':
    main()
