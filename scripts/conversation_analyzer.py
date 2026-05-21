#!/usr/bin/env python3
"""
Conversation Analyzer - Analisa conversas em busca de insights, itens de ação e updates
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path

# Configurações
MEMORY_DIR = Path.home() / ".openclaw" / "workspace" / "memory"
CONVO_LOG = MEMORY_DIR / "conversations.json"
OUTPUT_FILE = MEMORY_DIR / "analysis_output.json"

def load_conversations():
    """Carrega conversas do arquivo de log"""
    if CONVO_LOG.exists():
        with open(CONVO_LOG, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def extract_insights(text):
    """Extrai insights (preferências, correções, instruções)"""
    insights = []
    
    # Padrões de correção
    correction_patterns = [
        r'(?:não|errado|incorreto|corrigindo)[,:]\s*(.+?)(?:\.|$)',
        r'(?:quero que|prefiro que|gosto quando)[,:]\s*(.+?)(?:\.|$)',
        r'(?:nina[,:]\s*(?:lembra|anota|guarda))[,:]\s*(.+?)(?:\.|$)',
        r'(?:minha preferência é|eu prefiro|eu gosto de)[,:]\s*(.+?)(?:\.|$)',
    ]
    
    for pattern in correction_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            insight = match.group(1).strip()
            if len(insight) > 10:
                insights.append({
                    'type': 'correction' if 'não' in match.group(0).lower() else 'preference',
                    'content': insight,
                    'context': text[max(0, match.start()-50):match.end()+50]
                })
    
    return insights

def extract_action_items(text):
    """Extrai itens de ação"""
    actions = []
    
    # Padrões de ação
    action_patterns = [
        r'(?:nina[,;:]?\s+)(?:verifica|verifique|checa|cheque|confirma|confirme)[,:]?\s*(.+?)(?:\.|$)',
        r'(?:nina[,;:]?\s+)(?:lembra|lembre|anota|anote|guarda|guarde)[,:]?\s*(.+?)(?:\.|$)',
        r'(?:nina[,;:]?\s+)(?:faz|faça|precisa|precisamos)[,:]?\s*(.+?)(?:\.|$)',
    ]
    
    for pattern in action_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            action = match.group(1).strip()
            if len(action) > 5:
                actions.append({
                    'action': action,
                    'urgency': 'high' if any(word in text.lower() for word in ['urgente', 'agora', 'hoje', 'já']) else 'normal',
                    'context': text[max(0, match.start()-30):match.end()+30]
                })
    
    return actions

def extract_family_updates(text):
    """Extrai updates sobre a família"""
    updates = []
    
    # Padrões de updates familiares
    family_patterns = [
        r'(?:isabel|marcela|pedro)[,:]?\s*(vai|vamos|está|estamos|precisa|quer)[,:]?\s*(.+?)(?:\.|$)',
        r'(?:nossa rotina|a rotina|o plano)[,:]?\s*(.+?)(?:\.|$)',
        r'(?:vamos|vou)\s+(?:fazer|ir|viajar|mudar|começar)[,:]?\s*(.+?)(?:\.|$)',
    ]
    
    family_keywords = ['isabel', 'marcela', 'pedro', 'família', 'casa', 'rotina']
    
    for pattern in family_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            update = match.group(0).strip()
            if any(keyword in text.lower() for keyword in family_keywords):
                updates.append({
                    'type': 'family',
                    'content': update,
                    'people_mentioned': [p for p in ['isabel', 'marcela', 'pedro'] if p in text.lower()],
                    'context': text
                })
    
    return updates

def analyze_conversations():
    """Analisa todas as conversas e retorna resultados estruturados"""
    conversations = load_conversations()
    
    if not conversations:
        print("Nenhuma conversa encontrada para análise.")
        return None
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'total_conversations': len(conversations),
        'insights': [],
        'action_items': [],
        'family_updates': []
    }
    
    # Analisa cada conversa
    for conv in conversations:
        text = conv.get('content', '') or conv.get('message', '') or str(conv)
        
        # Extrai diferentes tipos de informação
        insights = extract_insights(text)
        actions = extract_action_items(text)
        updates = extract_family_updates(text)
        
        results['insights'].extend(insights)
        results['action_items'].extend(actions)
        results['family_updates'].extend(updates)
    
    # Salva resultados
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    return results

def main():
    import sys
    
    if '--analyze' in sys.argv:
        results = analyze_conversations()
        if results:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print(json.dumps({
                'timestamp': datetime.now().isoformat(),
                'status': 'no_data',
                'message': 'Nenhuma conversa encontrada'
            }))
    else:
        print("Uso: conversation_analyzer.py --analyze")

if __name__ == '__main__':
    main()
