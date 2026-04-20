#!/usr/bin/env python3
"""Local HTTP API for Mission Control control queue."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from control_queue import enqueue, queue


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-MC-Token")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(raw)


class Handler(BaseHTTPRequestHandler):
    server_version = "MissionControlAPI/1.0"

    def _read_json(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _authorized(self) -> bool:
        token = getattr(self.server, "mc_token", "")
        if not token:
            return True
        incoming = self.headers.get("X-MC-Token")
        return incoming == token

    def do_OPTIONS(self) -> None:  # noqa: N802
        json_response(self, HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            json_response(self, HTTPStatus.OK, {"ok": True})
            return

        if self.path == "/queue":
            if not self._authorized():
                json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            items = queue()
            json_response(self, HTTPStatus.OK, {"ok": True, "count": len(items), "queue": items})
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/enqueue":
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return

        if not self._authorized():
            json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return

        payload = self._read_json()
        if not payload:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        action = str(payload.get("action") or "").strip()
        body_payload = payload.get("payload")
        requested_by = str(payload.get("requestedBy") or "dashboard").strip() or "dashboard"

        if not action:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_action"})
            return

        if body_payload is None:
            body_payload = {}
        if not isinstance(body_payload, dict):
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "payload_must_be_object"})
            return

        # Basic validation to avoid poison commands from the dashboard
        if action == "todo.set_deadline":
            task_key = str(body_payload.get("taskKey") or "").strip()
            deadline = str(body_payload.get("deadline") or "").strip()
            if not task_key or task_key == "__none__":
                json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_taskKey"})
                return
            if not deadline:
                json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_deadline"})
                return

        item = enqueue(action=action, payload=body_payload, requested_by=requested_by)
        json_response(self, HTTPStatus.CREATED, {"ok": True, "item": item})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mission Control local control API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18791)
    parser.add_argument("--token", default=os.getenv("MC_CONTROL_TOKEN", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.mc_token = args.token

    print(f"Mission Control API listening on http://{args.host}:{args.port}")
    if args.token:
        print("Auth: enabled (X-MC-Token required)")
    else:
        print("Auth: disabled (no token configured)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
