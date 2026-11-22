"""数据源 API 管理中心 (支持可视化配置、.env 持久化、连通性探测与注册表映射查看)."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DataSourceItem:
    source_id: str
    name: str
    category: str
    endpoint_url: str
    env_key: str
    auth_env_key: str = ""
    description: str = ""
    internal_module: str = ""


DEFAULT_DATA_SOURCES: List[DataSourceItem] = [
    DataSourceItem(
        source_id="resin_control_plane",
        name="Resin 核心控制面与代理网关",
        category="核心网关",
        endpoint_url="http://127.0.0.1:2260/healthz",
        env_key="RESIN_CONTROL_URL",
        auth_env_key="RESIN_ADMIN_TOKEN",
        description="Resin 本地或远程控制平面 REST API (/api/v1/*) 与健康检查端点 (/healthz)。",
        internal_module="internal/api/server.go -> NewServerWithAddress",
    ),
    DataSourceItem(
        source_id="latency_probe_url",
        name="全局延迟探测权威端点 (Generate 204)",
        category="健康探测",
        endpoint_url="https://www.gstatic.com/generate_204",
        env_key="RESIN_LATENCY_TEST_URL",
        auth_env_key="",
        description="ProbeManager 主动探测节点 RTT 延迟与可用性的目标 URL（运行时可热更新）。",
        internal_module="internal/probe/manager.go -> ProbeConfig.LatencyTestURL",
    ),
    DataSourceItem(
        source_id="egress_trace_cloudflare",
        name="Cloudflare 出口 IP 与国家代码探测源",
        category="出口探测",
        endpoint_url="https://www.cloudflare.com/cdn-cgi/trace",
        env_key="RESIN_EGRESS_TRACE_URL",
        auth_env_key="",
        description="节点出口 IP 与 Location (loc) 探测接口，用于粘性路由同 IP 容灾切换与地区过滤。",
        internal_module="internal/probe/trace.go -> ParseCloudflareTrace",
    ),
    DataSourceItem(
        source_id="doh_dnspod",
        name="DNSPod DoH 安全 DNS 上游",
        category="安全 DNS",
        endpoint_url="https://doh.pub/dns-query",
        env_key="RESIN_NODE_DNS_PRIMARY",
        auth_env_key="",
        description="SingboxBuilder 默认首选 DoH 安全域名解析上游，防止节点域名解析污染。",
        internal_module="internal/outbound/secure_dns.go -> DefaultNodeDNSUpstreams[0]",
    ),
    DataSourceItem(
        source_id="doh_alidns",
        name="阿里云 AliDNS DoH 安全 DNS 上游",
        category="安全 DNS",
        endpoint_url="https://dns.alidns.com/dns-query",
        env_key="RESIN_NODE_DNS_SECONDARY",
        auth_env_key="",
        description="SingboxBuilder 备用 DoH 安全域名解析上游（支持顺序故障切换）。",
        internal_module="internal/outbound/secure_dns.go -> DefaultNodeDNSUpstreams[1]",
    ),
    DataSourceItem(
        source_id="geoip_mmdb",
        name="MaxMind GeoLite2 / Loyalsoldier GeoIP 数据库源",
        category="GeoIP 地理库",
        endpoint_url="https://raw.githubusercontent.com/Loyalsoldier/geoip/release/Country.mmdb",
        env_key="RESIN_GEOIP_MMDB_URL",
        auth_env_key="",
        description="用于将节点出口 IP 解析为 ISO 国家/地区代码以供 Platform 地区规则筛选。",
        internal_module="internal/geoip/geoip.go -> Service.UpdateNow",
    ),
    DataSourceItem(
        source_id="ipify_check",
        name="Ipify 公网出口 IP 验证服务",
        category="代理测试",
        endpoint_url="https://api.ipify.org?format=json",
        env_key="RESIN_TEST_TARGET_URL",
        auth_env_key="RESIN_PROXY_TOKEN",
        description="内置代理测试工坊用于校验 HTTP 正向代理、SOCKS5 与反向代理粘性会话出口 IP。",
        internal_module="desktop_gui/core_manager.py -> test_proxy_connection",
    ),
]


class DataSourceManager:
    """管理 Resin 外部数据源配置、.env 同步与连通性测试."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        if config_dir is None:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
            config_dir = base / "Resin"
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.config_dir / "datasources.json"
        self.env_path = self.config_dir / ".env"
        self.sources: Dict[str, DataSourceItem] = {s.source_id: s for s in DEFAULT_DATA_SOURCES}
        self.overrides: Dict[str, Dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        if self.json_path.exists():
            try:
                data = json.loads(self.json_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.overrides = data
            except Exception:
                pass

    def save(self) -> None:
        self.json_path.write_text(
            json.dumps(self.overrides, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_sources(self) -> List[Dict[str, Any]]:
        items = []
        for sid, src in self.sources.items():
            ov = self.overrides.get(sid, {})
            d = asdict(src)
            d["endpoint_url"] = ov.get("endpoint_url", src.endpoint_url)
            d["api_key"] = ov.get("api_key", os.environ.get(src.auth_env_key, "") if src.auth_env_key else "")
            items.append(d)
        return items

    def update_source(self, source_id: str, endpoint_url: str, api_key: str = "") -> None:
        self.overrides[source_id] = {
            "endpoint_url": endpoint_url.strip(),
            "api_key": api_key.strip(),
        }
        self.save()
        src = self.sources.get(source_id)
        if src:
            self._persist_env_kv(src.env_key, endpoint_url.strip())
            if src.auth_env_key and api_key.strip():
                self._persist_env_kv(src.auth_env_key, api_key.strip())

    def _persist_env_kv(self, key: str, value: str) -> None:
        if not key:
            return
        lines: List[str] = []
        if self.env_path.exists():
            lines = self.env_path.read_text(encoding="utf-8").splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def test_connectivity(self, source_id: str) -> Dict[str, Any]:
        all_items = {item["source_id"]: item for item in self.list_sources()}
        item = all_items.get(source_id)
        if not item:
            return {"ok": False, "status": 0, "latency_ms": 0.0, "message": "未找到数据源"}

        url = item["endpoint_url"]
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)",
        }
        if item.get("api_key"):
            headers["Authorization"] = f"Bearer {item['api_key']}"

        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = resp.status
                latency = round((time.time() - t0) * 1000, 1)
                return {
                    "ok": 200 <= status < 400,
                    "status": status,
                    "latency_ms": latency,
                    "message": f"HTTP {status} 响应正常 ({latency} ms)",
                }
        except urllib.error.HTTPError as he:
            latency = round((time.time() - t0) * 1000, 1)
            # DoH endpoints often return 400 on bare GET without ?dns= parameter, which proves reachability
            if he.code in (400, 405) and "dns-query" in url:
                return {
                    "ok": True,
                    "status": he.code,
                    "latency_ms": latency,
                    "message": f"DoH 端点在线可达 (HTTP {he.code}, {latency} ms)",
                }
            return {
                "ok": False,
                "status": he.code,
                "latency_ms": latency,
                "message": f"HTTP {he.code}: {he.reason}",
            }
        except Exception as exc:
            latency = round((time.time() - t0) * 1000, 1)
            return {
                "ok": False,
                "status": 0,
                "latency_ms": latency,
                "message": f"连接异常: {exc}",
            }
