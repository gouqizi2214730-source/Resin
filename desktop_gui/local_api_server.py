"""本地轻量 HTTP 与 OpenAI 兼容 API 守护服务 (127.0.0.1:8787)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from . import __app_name__, __version__
from .core_manager import ResinAPIClient, ResinCoreProcessManager
from .data_sources import DataSourceManager
from .llm_providers import LLMProviderManager


class LocalGatewayHTTPServer:
    """在后台守护线程中暴露 /health, /v1/models, /v1/chat/completions, /api/providers, /api/datasources, /api/resin/status."""

    def __init__(
        self,
        llm_mgr: LLMProviderManager,
        ds_mgr: DataSourceManager,
        core_mgr: Optional[ResinCoreProcessManager] = None,
        api_client: Optional[ResinAPIClient] = None,
        host: str = "127.0.0.1",
        port: int = 8787,
    ) -> None:
        self.llm_mgr = llm_mgr
        self.ds_mgr = ds_mgr
        self.core_mgr = core_mgr
        self.api_client = api_client
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> int:
        if self._server is not None:
            return self.port

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return  # Silent background daemon logging

            def _send_json(self, code: int, payload: Any) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()

            def do_GET(self) -> None:
                if self.path in ("/health", "/healthz"):
                    core_running = outer.core_mgr.is_running() if outer.core_mgr else False
                    self._send_json(
                        200,
                        {
                            "status": "ok",
                            "app": __app_name__,
                            "version": __version__,
                            "resin_core_running": core_running,
                            "timestamp": int(time.time()),
                        },
                    )
                    return

                if self.path == "/v1/models":
                    models = []
                    for p in outer.llm_mgr.list_providers():
                        for m in p.get("models", []):
                            models.append(
                                {
                                    "id": f"{p['provider_id']}/{m}",
                                    "object": "model",
                                    "owned_by": p["provider_id"],
                                }
                            )
                    self._send_json(200, {"object": "list", "data": models})
                    return

                if self.path == "/api/providers":
                    self._send_json(200, {"providers": outer.llm_mgr.list_providers()})
                    return

                if self.path == "/api/datasources":
                    self._send_json(200, {"datasources": outer.ds_mgr.list_sources()})
                    return

                if self.path == "/api/resin/status":
                    status_data = {"core_process_running": outer.core_mgr.is_running() if outer.core_mgr else False}
                    if outer.api_client:
                        ok, snap = outer.api_client.get_snapshot_node_pool()
                        status_data["control_plane_reachable"] = ok
                        status_data["node_pool_snapshot"] = snap
                    self._send_json(200, status_data)
                    return

                self._send_json(404, {"error": "Not Found", "path": self.path})

            def do_POST(self) -> None:
                if self.path == "/v1/chat/completions":
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                    try:
                        req_data = json.loads(raw)
                    except Exception:
                        req_data = {}
                    messages = req_data.get("messages", [{"role": "user", "content": "你好"}])
                    model = req_data.get("model")
                    provider_id = req_data.get("provider")
                    if model and "/" in model and not provider_id:
                        cand_p, cand_m = model.split("/", 1)
                        if cand_p in outer.llm_mgr.providers:
                            provider_id = cand_p
                            model = cand_m
                    res = outer.llm_mgr.chat_completion(
                        messages=messages,
                        provider_id=provider_id,
                        model=model,
                        temperature=float(req_data.get("temperature", 0.3)),
                    )
                    self._send_json(
                        200,
                        {
                            "id": f"chatcmpl-resin-{int(time.time())}",
                            "object": "chat.completion",
                            "created": int(time.time()),
                            "model": res.get("model", "default"),
                            "provider": res.get("provider", "local"),
                            "ok": res.get("ok", False),
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": res.get("content", "")},
                                    "finish_reason": "stop",
                                }
                            ],
                        },
                    )
                    return

                self._send_json(404, {"error": "Not Found", "path": self.path})

        for candidate_port in (self.port, 8788, 8789, 0):
            try:
                self._server = ThreadingHTTPServer((self.host, candidate_port), Handler)
                self.port = self._server.server_address[1]
                break
            except OSError:
                continue

        if self._server is not None:
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
