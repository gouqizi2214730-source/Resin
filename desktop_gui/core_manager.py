"""Resin 核心引擎进程管理器、AI 自动巡检自愈守护线程与全功能 Control Plane API 客户端."""

from __future__ import annotations

import base64
import collections
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class ResinCoreProcessManager:
    """管理内置 resin-core.exe 守护进程、.env 配置持久化、开机自启与 Windows 系统代理设置."""

    def __init__(self, app_dir: Optional[Path] = None, data_dir: Optional[Path] = None) -> None:
        if app_dir is None:
            if getattr(sys, "frozen", False):
                app_dir = Path(sys.executable).resolve().parent
            else:
                app_dir = Path(__file__).resolve().parent.parent
        self.app_dir = Path(app_dir)

        if data_dir is None:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
            data_dir = base / "Resin"
        self.data_dir = Path(data_dir)
        self.state_dir = self.data_dir / "data" / "state"
        self.cache_dir = self.data_dir / "data" / "cache"
        self.log_dir = self.data_dir / "data" / "log"
        for d in (self.data_dir, self.state_dir, self.cache_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.env_file = self.data_dir / ".env"
        self.proc: Optional[subprocess.Popen] = None
        self.log_buffer: Deque[str] = collections.deque(maxlen=600)
        self._lock = threading.Lock()
        self.ensure_default_env()

    def find_core_binary(self) -> Optional[Path]:
        candidates = [
            self.app_dir / "resin-core.exe",
            self.app_dir / "resin.exe",
            self.app_dir / "_internal" / "resin-core.exe",
            self.app_dir / "resin-core",
            self.app_dir / "resin",
            self.app_dir / "build" / "resin-windows-amd64.exe",
            self.app_dir / "build" / "resin-linux-amd64",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                if c.name.lower() == "resin.exe" and getattr(sys, "frozen", False):
                    if c.resolve() == Path(sys.executable).resolve():
                        continue
                return c
        return None

    def ensure_default_env(self) -> Dict[str, str]:
        defaults = {
            "RESIN_ADMIN_TOKEN": "admin123",
            "RESIN_PROXY_TOKEN": "my-token",
            "RESIN_LISTEN_ADDRESS": "0.0.0.0",
            "RESIN_PORT": "2260",
            "RESIN_STATE_DIR": str(self.state_dir).replace("\\", "/"),
            "RESIN_CACHE_DIR": str(self.cache_dir).replace("\\", "/"),
            "RESIN_LOG_DIR": str(self.log_dir).replace("\\", "/"),
            "RESIN_PROBE_CONCURRENCY": "500",
            "RESIN_PROBE_TIMEOUT": "15s",
            "RESIN_RESOURCE_FETCH_TIMEOUT": "30s",
            "RESIN_DEFAULT_PLATFORM_STICKY_TTL": "168h",
            "RESIN_DEFAULT_PLATFORM_ALLOCATION_POLICY": "BALANCED",
            "RESIN_DEFAULT_PLATFORM_REVERSE_PROXY_MISS_ACTION": "TREAT_AS_EMPTY",
            "RESIN_DEFAULT_PLATFORM_REVERSE_PROXY_EMPTY_ACCOUNT_BEHAVIOR": "ACCOUNT_HEADER_RULE",
            "RESIN_DEFAULT_PLATFORM_REVERSE_PROXY_FIXED_ACCOUNT_HEADER": "Authorization",
            "RESIN_PROXY_BYPASS": "localhost;127.*;10.*;172.16.0.0/12;192.168.*;<local>",
        }
        current = self.read_env()
        updated = False
        for k, v in defaults.items():
            if k not in current:
                current[k] = v
                updated = True
        if updated or not self.env_file.exists():
            self.write_env(current)
        return current

    def read_env(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if not self.env_file.exists():
            return result
        for line in self.env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            result[k.strip()] = v.strip().strip('"').strip("'")
        return result

    def write_env(self, env_dict: Dict[str, str]) -> None:
        lines = ["# Resin 核心网关启动环境配置文件 (.env)"]
        for k, v in env_dict.items():
            lines.append(f"{k}={v}")
        self.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> Tuple[bool, str]:
        with self._lock:
            if self.is_running():
                return True, f"本地 Resin 引擎已在运行中 (PID: {self.proc.pid})"
            binary = self.find_core_binary()
            if not binary:
                return False, "未找到本地 resin-core 核心可执行文件，您仍可连接远程 Resin 网关使用全部管理功能。"

            env_cfg = self.ensure_default_env()
            child_env = os.environ.copy()
            child_env.update(env_cfg)

            try:
                self.proc = subprocess.Popen(
                    [str(binary)],
                    cwd=str(self.data_dir),
                    env=child_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=CREATE_NO_WINDOW,
                )
                threading.Thread(target=self._stream_logs, daemon=True).start()
                self.log_buffer.append(
                    f"[{time.strftime('%H:%M:%S')}] 已启动 resin-core 进程 (PID={self.proc.pid}, 端口={env_cfg.get('RESIN_PORT', '2260')})"
                )
                return True, f"Resin 核心引擎启动成功 (PID: {self.proc.pid})"
            except Exception as exc:
                self.log_buffer.append(f"[{time.strftime('%H:%M:%S')}] 启动失败: {exc}")
                return False, f"启动失败: {exc}"

    def _stream_logs(self) -> None:
        p = self.proc
        if not p or not p.stdout:
            return
        try:
            for line in p.stdout:
                self.log_buffer.append(line.rstrip("\r\n"))
        except Exception:
            pass

    def stop(self) -> Tuple[bool, str]:
        with self._lock:
            if not self.is_running() or self.proc is None:
                return True, "本地 Resin 引擎当前未运行"
            pid = self.proc.pid
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                self.log_buffer.append(f"[{time.strftime('%H:%M:%S')}] 已停止 resin-core 进程 (PID={pid})")
                self.proc = None
                return True, f"已停止本地 Resin 引擎 (PID: {pid})"
            except Exception as exc:
                return False, f"停止进程异常: {exc}"

    def restart(self) -> Tuple[bool, str]:
        self.stop()
        time.sleep(0.4)
        return self.start()

    def get_recent_logs(self) -> str:
        return "\n".join(self.log_buffer)

    @staticmethod
    def set_windows_system_proxy(enable: bool, host: str = "127.0.0.1", port: int = 2260) -> Tuple[bool, str]:
        if sys.platform != "win32":
            return False, "系统代理快捷开关仅在 Windows 系统上受支持"
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enable else 0)
                if enable:
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
                    winreg.SetValueEx(
                        key,
                        "ProxyOverride",
                        0,
                        winreg.REG_SZ,
                        "localhost;127.*;10.*;172.16.*;192.168.*;<local>",
                    )
            state_str = f"已开启 Windows 系统代理 ({host}:{port})" if enable else "已关闭 Windows 系统代理"
            return True, state_str
        except Exception as exc:
            return False, f"修改系统代理注册表失败: {exc}"

    @staticmethod
    def is_windows_startup_enabled() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, "ResinProxyGateway")
                return bool(val)
        except Exception:
            return False

    def set_windows_startup(self, enable: bool) -> Tuple[bool, str]:
        if sys.platform != "win32":
            return False, "开机自启注册表配置仅在 Windows 系统上受支持"
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            exe_path = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else (self.app_dir / "Resin.exe")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, "ResinProxyGateway", 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
                    return True, "已开启 Windows 开机自动启动（开机后静默驻留系统托盘）"
                else:
                    try:
                        winreg.DeleteValue(key, "ResinProxyGateway")
                    except FileNotFoundError:
                        pass
                    return True, "已关闭 Windows 开机自动启动"
        except Exception as exc:
            return False, f"配置开机自启失败: {exc}"


class ResinAPIClient:
    """完整封装 Resin Control Plane REST API (/healthz 与 /api/v1/*)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:2260",
        admin_token: str = "admin123",
        proxy_token: str = "my-token",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.proxy_token = proxy_token

    def configure(self, base_url: str, admin_token: str, proxy_token: str = "") -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.admin_token = admin_token.strip()
        self.proxy_token = proxy_token.strip()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        timeout: int = 12,
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}{path}"
        if params:
            clean_params = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean_params:
                url += "?" + urllib.parse.urlencode(clean_params)

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)",
        }
        if self.admin_token:
            headers["Authorization"] = f"Bearer {self.admin_token}"

        data_bytes = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if not raw.strip():
                    return True, {"status": "ok", "http_code": resp.status}
                try:
                    return True, json.loads(raw)
                except Exception:
                    return True, {"raw": raw, "http_code": resp.status}
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message") or err_json.get("error") or err_body
            except Exception:
                msg = err_body or he.reason
            return False, f"HTTP {he.code}: {msg}"
        except Exception as exc:
            return False, f"连接错误: {exc}"

    # ---- 1. Health & System Config ----
    def healthz(self) -> Tuple[bool, Any]:
        return self._request("GET", "/healthz", timeout=4)

    def get_system_info(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/system/info")

    def get_system_config(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/system/config")

    def get_system_default_config(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/system/config/default")

    def get_system_env_config(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/system/config/env")

    def patch_system_config(self, patch: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request("PATCH", "/api/v1/system/config", body=patch)

    # ---- 2. Subscriptions ----
    def list_subscriptions(self, keyword: str = "", enabled: Optional[str] = None) -> Tuple[bool, Any]:
        params: Dict[str, Any] = {"limit": 200, "offset": 0}
        if keyword:
            params["keyword"] = keyword
        if enabled in ("true", "false"):
            params["enabled"] = enabled
        return self._request("GET", "/api/v1/subscriptions", params=params)

    def create_subscription(self, payload: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request("POST", "/api/v1/subscriptions", body=payload)

    def update_subscription(self, sub_id: str, patch: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request("PATCH", f"/api/v1/subscriptions/{sub_id}", body=patch)

    def delete_subscription(self, sub_id: str) -> Tuple[bool, Any]:
        return self._request("DELETE", f"/api/v1/subscriptions/{sub_id}")

    def refresh_subscription(self, sub_id: str) -> Tuple[bool, Any]:
        return self._request("POST", f"/api/v1/subscriptions/{sub_id}/actions/refresh", body={}, timeout=35)

    def cleanup_subscription_circuit_open(self, sub_id: str) -> Tuple[bool, Any]:
        return self._request("POST", f"/api/v1/subscriptions/{sub_id}/actions/cleanup-circuit-open-nodes", body={})

    # ---- 3. Platforms ----
    def list_platforms(self, keyword: str = "") -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/platforms", params={"keyword": keyword, "limit": 200, "offset": 0})

    def create_platform(self, payload: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request("POST", "/api/v1/platforms", body=payload)

    def update_platform(self, platform_id: str, patch: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request("PATCH", f"/api/v1/platforms/{platform_id}", body=patch)

    def delete_platform(self, platform_id: str) -> Tuple[bool, Any]:
        return self._request("DELETE", f"/api/v1/platforms/{platform_id}")

    def reset_platform(self, platform_id: str) -> Tuple[bool, Any]:
        return self._request("POST", f"/api/v1/platforms/{platform_id}/actions/reset-to-default", body={})

    def rebuild_platform_view(self, platform_id: str) -> Tuple[bool, Any]:
        return self._request("POST", f"/api/v1/platforms/{platform_id}/actions/rebuild-routable-view", body={})

    def preview_platform_filter(self, regex_filters: List[str], region_filters: List[str]) -> Tuple[bool, Any]:
        body = {
            "platform_spec": {
                "regex_filters": regex_filters,
                "region_filters": region_filters,
            }
        }
        return self._request("POST", "/api/v1/platforms/preview-filter?limit=200&offset=0", body=body)

    # ---- 4. Nodes & Active Probes ----
    def list_nodes(self, filters: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        params: Dict[str, Any] = {"limit": 200, "offset": 0}
        if filters:
            params.update(filters)
        return self._request("GET", "/api/v1/nodes", params=params)

    def get_node(self, node_hash: str) -> Tuple[bool, Any]:
        return self._request("GET", f"/api/v1/nodes/{node_hash}")

    def probe_node_egress(self, node_hash: str) -> Tuple[bool, Any]:
        return self._request("POST", f"/api/v1/nodes/{node_hash}/actions/probe-egress", body={}, timeout=25)

    def probe_node_latency(self, node_hash: str) -> Tuple[bool, Any]:
        return self._request("POST", f"/api/v1/nodes/{node_hash}/actions/probe-latency", body={}, timeout=25)

    # ---- 5. Sticky Leases & IP Load ----
    def list_leases(self, platform_id: str, account: str = "", fuzzy: bool = True) -> Tuple[bool, Any]:
        params: Dict[str, Any] = {"limit": 200, "offset": 0}
        if account:
            params["account"] = account
            params["fuzzy"] = "true" if fuzzy else "false"
        return self._request("GET", f"/api/v1/platforms/{platform_id}/leases", params=params)

    def delete_lease(self, platform_id: str, account: str) -> Tuple[bool, Any]:
        enc_acc = urllib.parse.quote(account, safe="")
        return self._request("DELETE", f"/api/v1/platforms/{platform_id}/leases/{enc_acc}")

    def delete_all_leases(self, platform_id: str) -> Tuple[bool, Any]:
        return self._request("DELETE", f"/api/v1/platforms/{platform_id}/leases")

    def get_ip_load(self, platform_id: str) -> Tuple[bool, Any]:
        return self._request("GET", f"/api/v1/platforms/{platform_id}/ip-load", params={"limit": 200, "offset": 0})

    def inherit_lease(self, platform_name: str, parent_account: str, new_account: str) -> Tuple[bool, Any]:
        token = self.proxy_token or "my-token"
        enc_plat = urllib.parse.quote(platform_name, safe="")
        return self._request(
            "POST",
            f"/{token}/api/v1/{enc_plat}/actions/inherit-lease",
            body={"parent_account": parent_account, "new_account": new_account},
        )

    # ---- 6. Multi-Port Endpoints ----
    def list_endpoints(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/endpoints", params={"limit": 200, "offset": 0})

    def create_endpoint(self, payload: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request("POST", "/api/v1/endpoints", body=payload)

    def update_endpoint(self, endpoint_id: str, patch: Dict[str, Any]) -> Tuple[bool, Any]:
        return self._request("PATCH", f"/api/v1/endpoints/{endpoint_id}", body=patch)

    def delete_endpoint(self, endpoint_id: str) -> Tuple[bool, Any]:
        return self._request("DELETE", f"/api/v1/endpoints/{endpoint_id}")

    # ---- 7. Account Header Rules ----
    def list_rules(self, keyword: str = "") -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/account-header-rules", params={"keyword": keyword, "limit": 200, "offset": 0})

    def upsert_rule(self, url_prefix: str, headers: List[str]) -> Tuple[bool, Any]:
        clean_prefix = url_prefix.strip().lstrip("/")
        if not clean_prefix:
            clean_prefix = "*"
        return self._request("PUT", f"/api/v1/account-header-rules/{clean_prefix}", body={"headers": headers})

    def delete_rule(self, url_prefix: str) -> Tuple[bool, Any]:
        clean_prefix = url_prefix.strip().lstrip("/")
        return self._request("DELETE", f"/api/v1/account-header-rules/{clean_prefix}")

    def resolve_rule(self, test_url: str) -> Tuple[bool, Any]:
        return self._request("POST", "/api/v1/account-header-rules:resolve", body={"url": test_url})

    # ---- 8. Structured Request Logs & Payload Auditing ----
    def list_request_logs(self, filters: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        params: Dict[str, Any] = {"limit": 100}
        if filters:
            params.update(filters)
        return self._request("GET", "/api/v1/request-logs", params=params)

    def get_request_log_payloads(self, log_id: str) -> Tuple[bool, Any]:
        ok, data = self._request("GET", f"/api/v1/request-logs/{log_id}/payloads")
        if not ok or not isinstance(data, dict):
            return ok, data
        decoded = dict(data)
        for field_b64, field_text in [
            ("req_headers_b64", "req_headers_text"),
            ("req_body_b64", "req_body_text"),
            ("resp_headers_b64", "resp_headers_text"),
            ("resp_body_b64", "resp_body_text"),
        ]:
            raw_b64 = data.get(field_b64, "")
            if raw_b64:
                try:
                    decoded[field_text] = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
                except Exception:
                    decoded[field_text] = "<Base64 解码失败>"
            else:
                decoded[field_text] = ""
        return True, decoded

    # ---- 9. GeoIP Service ----
    def get_geoip_status(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/geoip/status")

    def lookup_geoip(self, ip: str) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/geoip/lookup", params={"ip": ip})

    def update_geoip_now(self) -> Tuple[bool, Any]:
        return self._request("POST", "/api/v1/geoip/actions/update-now", body={}, timeout=40)

    # ---- 10. Realtime & Historical Metrics ----
    def get_snapshot_node_pool(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/metrics/snapshots/node-pool")

    def get_snapshot_latency_distribution(self, platform_id: str = "") -> Tuple[bool, Any]:
        params = {"platform_id": platform_id} if platform_id else None
        return self._request("GET", "/api/v1/metrics/snapshots/node-latency-distribution", params=params)

    def get_realtime_throughput(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/metrics/realtime/throughput")

    def get_realtime_connections(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/metrics/realtime/connections")

    def get_realtime_leases(self, platform_id: str = "") -> Tuple[bool, Any]:
        params = {"platform_id": platform_id} if platform_id else None
        return self._request("GET", "/api/v1/metrics/realtime/leases", params=params)

    def get_history_traffic(self) -> Tuple[bool, Any]:
        return self._request("GET", "/api/v1/metrics/history/traffic")

    def get_history_requests(self, platform_id: str = "") -> Tuple[bool, Any]:
        params = {"platform_id": platform_id} if platform_id else None
        return self._request("GET", "/api/v1/metrics/history/requests", params=params)

    # ---- 11. Proxy Connectivity & Sticky Session Tester ----
    def test_proxy_connection(
        self,
        mode: str = "http_forward",
        platform_name: str = "Default",
        account: str = "test_user_01",
        target_url: str = "https://api.ipify.org?format=json",
    ) -> Dict[str, Any]:
        parsed = urllib.parse.urlparse(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 2260
        token = self.proxy_token

        identity = f"{platform_name}.{account}" if account else platform_name
        t0 = time.time()
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)",
        }

        try:
            if mode == "http_forward":
                auth_part = f"{identity}:{token}@" if token else (f"{identity}@" if identity else "")
                proxy_url = f"http://{auth_part}{host}:{port}"
                proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
                opener = urllib.request.build_opener(proxy_handler)
                req = urllib.request.Request(target_url, headers=headers)
                with opener.open(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    return {
                        "ok": True,
                        "mode": "HTTP 正向粘性代理",
                        "proxy_endpoint": proxy_url,
                        "status": resp.status,
                        "latency_ms": round((time.time() - t0) * 1000, 1),
                        "response": body,
                    }
            else:
                t_parsed = urllib.parse.urlparse(target_url)
                scheme = t_parsed.scheme or "https"
                rest = f"{t_parsed.netloc}{t_parsed.path}"
                if t_parsed.query:
                    rest += f"?{t_parsed.query}"
                token_seg = token if token else "-"
                if mode == "reverse_header":
                    rev_url = f"http://{host}:{port}/{token_seg}/{platform_name}/{scheme}/{rest}"
                    if account:
                        headers["X-Resin-Account"] = account
                else:
                    rev_url = f"http://{host}:{port}/{token_seg}/{identity}/{scheme}/{rest}"
                req = urllib.request.Request(rev_url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    return {
                        "ok": True,
                        "mode": "HTTP 反向粘性代理",
                        "proxy_endpoint": rev_url,
                        "status": resp.status,
                        "latency_ms": round((time.time() - t0) * 1000, 1),
                        "response": body,
                    }
        except Exception as exc:
            return {
                "ok": False,
                "mode": mode,
                "status": 0,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "response": f"代理请求失败: {exc}",
            }


class AutoHealWatchdog:
    """AI 自动巡检与节点池故障自愈守护引擎."""

    def __init__(
        self,
        api_client: ResinAPIClient,
        core_mgr: Optional[ResinCoreProcessManager] = None,
        interval_sec: int = 180,
        min_healthy_ratio: float = 0.4,
    ) -> None:
        self.api = api_client
        self.core_mgr = core_mgr
        self.interval_sec = interval_sec
        self.min_healthy_ratio = min_healthy_ratio
        self.enabled: bool = True
        self.history: Deque[str] = collections.deque(maxlen=150)
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()

    def _loop(self) -> None:
        while not self._stop_evt.wait(self.interval_sec):
            if self.enabled:
                self.run_patrol_once()

    def run_patrol_once(self) -> Dict[str, Any]:
        ts = time.strftime("%H:%M:%S")
        actions_taken: List[str] = []

        ok_h, _ = self.api.healthz()
        if not ok_h:
            if self.core_mgr and self.core_mgr.find_core_binary() and not self.core_mgr.is_running():
                started, msg = self.core_mgr.start()
                actions_taken.append(f"检测到本地核心未运行，已自动拉起: {msg}")
            else:
                msg = f"[{ts}] 巡检跳过: 控制面未连接"
                self.history.append(msg)
                return {"ok": False, "actions": actions_taken, "summary": msg}

        ok_s, subs_data = self.api.list_subscriptions()
        cleaned_total = 0
        refreshed_subs = 0
        if ok_s and isinstance(subs_data, dict):
            for s in subs_data.get("items", []):
                if not s.get("enabled"):
                    continue
                sid = s.get("id", "")
                sname = s.get("name", sid)
                total_n = int(s.get("node_count", 0))
                healthy_n = int(s.get("healthy_node_count", 0))
                ratio = (healthy_n / total_n) if total_n > 0 else 1.0

                if total_n > 0 and healthy_n < total_n:
                    ok_c, c_res = self.api.cleanup_subscription_circuit_open(sid)
                    if ok_c and isinstance(c_res, dict) and c_res.get("cleaned_count", 0) > 0:
                        cnt = c_res["cleaned_count"]
                        cleaned_total += cnt
                        actions_taken.append(f"订阅「{sname}」自动清理熔断节点 {cnt} 个")

                if total_n == 0 or ratio < self.min_healthy_ratio:
                    self.api.refresh_subscription(sid)
                    refreshed_subs += 1
                    actions_taken.append(f"订阅「{sname}」健康率 ({ratio*100:.0f}%) 低于阈值，已触发自动同步刷新")

        ok_n, nodes_data = self.api.list_nodes({"circuit_open": "true"})
        probed_nodes = 0
        if ok_n and isinstance(nodes_data, dict):
            for n in (nodes_data.get("items") or [])[:5]:
                nh = n.get("node_hash", "")
                if nh:
                    self.api.probe_node_latency(nh)
                    probed_nodes += 1
            if probed_nodes > 0:
                actions_taken.append(f"已对 {probed_nodes} 个熔断节点发起主动延迟恢复探测")

        ok_p, plats_data = self.api.list_platforms()
        if ok_p and isinstance(plats_data, dict) and (cleaned_total > 0 or refreshed_subs > 0 or probed_nodes > 0):
            for p in plats_data.get("items", []):
                pid = p.get("id", "")
                if pid:
                    self.api.rebuild_platform_view(pid)
            actions_taken.append("已自动重建全部 Platform 可路由隔离池视图")

        _, snap = self.api.get_snapshot_node_pool()
        snap_info = ""
        if isinstance(snap, dict):
            snap_info = f"总节点={snap.get('total_nodes', 0)}, 健康={snap.get('healthy_nodes', 0)}, 独立IP={snap.get('egress_ip_count', 0)}"

        if not actions_taken:
            summary = f"[{ts}] AI 巡检通过: 节点池健康稳定 ({snap_info})，无需自愈操作。"
        else:
            summary = f"[{ts}] AI 自愈完成 ({snap_info}): " + "；".join(actions_taken)

        self.history.append(summary)
        if self.core_mgr:
            self.core_mgr.log_buffer.append(summary)
        return {
            "ok": True,
            "timestamp": ts,
            "actions": actions_taken,
            "summary": summary,
            "history": list(self.history),
        }
