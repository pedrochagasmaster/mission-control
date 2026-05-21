#!/usr/bin/env python3
"""
Watchdog para Tracking Despesas (API + Frontend)
Verifica se os serviços estão rodando e os inicia se necessário.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# O projeto real está em my_project_dir/tracking_despesas
ROOT = Path("/home/pedro/my_project_dir/tracking_despesas")
LOG_DIR = ROOT / "logs"
API_PORT = 8000
UI_PORT = 5173


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def pid_for_port(port: int) -> int | None:
    try:
        out = subprocess.check_output(
            ["bash", "-lc", f"ss -ltnp '( sport = :{port} )'"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None

    for line in out.splitlines():
        marker = "pid="
        if marker not in line:
            continue
        rest = line.split(marker, 1)[1]
        pid_part = rest.split(",", 1)[0].strip()
        if pid_part.isdigit():
            return int(pid_part)
    return None


def start_nohup(command: str, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as logf, open(os.devnull, "rb") as devnull:
        proc = subprocess.Popen(
            ["bash", "-lc", f"cd {shlex.quote(str(ROOT))} && exec nohup {command}"],
            stdin=devnull,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def wait_for_port(port: int, timeout_s: int = 25) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_port_open(port):
            return True
        time.sleep(0.5)
    return False


def ensure_service(name: str, port: int, start_cmd: str, log_file: Path, should_start: bool) -> dict[str, Any]:
    running = is_port_open(port)
    started = False
    start_error = None
    pid = pid_for_port(port)

    if not running and should_start:
        try:
            pid = start_nohup(start_cmd, log_file)
            running = wait_for_port(port)
            started = running
            if running:
                pid = pid_for_port(port) or pid
            else:
                start_error = f"{name} did not open port {port} within timeout"
        except Exception as exc:
            start_error = str(exc)
            running = False

    return {
        "name": name,
        "port": port,
        "running": running,
        "started_now": started,
        "pid": pid,
        "log_file": str(log_file),
        "start_error": start_error,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watchdog para Tracking Despesas (API + Frontend)"
    )
    parser.add_argument("--ensure-ui", action="store_true", help="Garante que UI esteja rodando")
    parser.add_argument("--ensure-api", action="store_true", help="Garante que API esteja rodando")
    parser.add_argument("--api-port", type=int, default=API_PORT)
    parser.add_argument("--ui-port", type=int, default=UI_PORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    
    # Se --ensure-ui for passado, garantimos ambos (API é dependência da UI)
    ensure_api = args.ensure_api or args.ensure_ui
    ensure_ui = args.ensure_ui
    
    services_status = {}
    errors = []

    # Verifica/inicia API
    if ensure_api:
        api_cmd = f"uv run python -m uvicorn api:app --host 0.0.0.0 --port {args.api_port}"
        api_info = ensure_service(
            name="api",
            port=args.api_port,
            start_cmd=api_cmd,
            log_file=LOG_DIR / "api.nohup.log",
            should_start=True,
        )
        services_status["api"] = api_info
        if api_info.get("start_error"):
            errors.append(f"API: {api_info['start_error']}")

    # Verifica/inicia Frontend
    if ensure_ui:
        ui_cmd = (
            f"npm --prefix {shlex.quote(str(ROOT / 'dashboard'))} run dev -- "
            f"--host 0.0.0.0 --port {args.ui_port}"
        )
        ui_info = ensure_service(
            name="frontend",
            port=args.ui_port,
            start_cmd=ui_cmd,
            log_file=LOG_DIR / "frontend.nohup.log",
            should_start=True,
        )
        services_status["frontend"] = ui_info
        if ui_info.get("start_error"):
            errors.append(f"Frontend: {ui_info['start_error']}")

    # Verifica estado final
    api_running = is_port_open(args.api_port)
    ui_running = is_port_open(args.ui_port) if ensure_ui else True

    # Se tudo OK e não houve erros, retorna NO_REPLY
    if api_running and ui_running and not errors:
        print("NO_REPLY")
        return 0
    
    # Se houve erros, retorna detalhes
    if errors:
        print(f"ERROS: {'; '.join(errors)}")
        return 1
    
    # Se não está rodando mas não houve erro explícito
    if not api_running:
        print(f"ERRO: API não está respondendo na porta {args.api_port}")
        return 1
    if ensure_ui and not ui_running:
        print(f"ERRO: Frontend não está respondendo na porta {args.ui_port}")
        return 1
    
    print("NO_REPLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
