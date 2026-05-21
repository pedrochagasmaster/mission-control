#!/usr/bin/env python3
"""Simple memory logging utility for cron jobs and events."""

import argparse
import json
import os
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description='Log events to memory')
    parser.add_argument('--type', required=True, help='Event type')
    parser.add_argument('--channel', required=True, help='Channel')
    parser.add_argument('--chat-id', required=True, help='Chat ID')
    parser.add_argument('--text', required=True, help='Log text')
    parser.add_argument('--importance', default='low', help='Importance level')
    parser.add_argument('--tags', help='Comma-separated tags')
    
    args = parser.parse_args()
    
    # Create memory directory if needed
    memory_dir = '/home/pedro/.openclaw/workspace/memory'
    os.makedirs(memory_dir, exist_ok=True)
    
    # Log entry
    entry = {
        'timestamp': datetime.now().isoformat(),
        'type': args.type,
        'channel': args.channel,
        'chat_id': args.chat_id,
        'text': args.text,
        'importance': args.importance,
        'tags': args.tags.split(',') if args.tags else []
    }
    
    # Append to daily log
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(memory_dir, f'{today}.jsonl')
    
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    print(f"✓ Logged to {log_file}")

if __name__ == '__main__':
    main()
