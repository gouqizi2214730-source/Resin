"""统一本地与云端大模型 API 管理模块 (支持 Ollama/LM Studio/vLLM 免 Key 直连与主流云端大模型)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ProviderSpec:
    provider_id: str
    name: str
    base_url: str
    default_model: str
    models: List[str] = field(default_factory=list)
    requires_key: bool = True
    env_key: str = ""
    category: str = "cloud"  # "local" | "cloud"
    description: str = ""


BUILTIN_PROVIDERS: List[ProviderSpec] = [
    ProviderSpec(
        provider_id="ollama",
        name="Ollama (本地免 Key 直连)",
        base_url="http://127.0.0.1:11434/v1",
        default_model="qwen2.5:7b",
        models=["qwen2.5:7b", "qwen2.5-coder:7b", "deepseek-r1:8b", "llama3.1:8b"],
        requires_key=False,
        env_key="OLLAMA_API_KEY",
        category="local",
        description="本地 Ollama 推理服务，默认端口 11434，无需 API Key 即可进行代理规则生成与日志诊断。",
    ),
    ProviderSpec(
        provider_id="lmstudio",
        name="LM Studio (本地免 Key 直连)",
        base_url="http://127.0.0.1:1234/v1",
        default_model="local-model",
        models=["local-model", "qwen2.5-7b-instruct", "deepseek-r1-distill-qwen-7b"],
        requires_key=False,
        env_key="LMSTUDIO_API_KEY",
        category="local",
        description="本地 LM Studio OpenAI 兼容推理服务器，默认端口 1234。",
    ),
    ProviderSpec(
        provider_id="vllm",
        name="vLLM (本地/内网高并发推理)",
        base_url="http://127.0.0.1:8000/v1",
        default_model="Qwen/Qwen2.5-7B-Instruct",
        models=["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"],
        requires_key=False,
        env_key="VLLM_API_KEY",
        category="local",
        description="本地或局域网 vLLM OpenAI 兼容服务端，默认端口 8000。",
    ),
    ProviderSpec(
        provider_id="deepseek",
        name="DeepSeek (深度求索官方 API)",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-reasoner"],
        requires_key=True,
        env_key="DEEPSEEK_API_KEY",
        category="cloud",
        description="DeepSeek-V3 / R1 官方云端 API，擅长生成复杂正则表达式与排查网络协议错误。",
    ),
    ProviderSpec(
        provider_id="dashscope",
        name="阿里云百炼 / 通义千问 (DashScope)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        models=["qwen-plus", "qwen-max", "qwen-turbo", "qwen2.5-coder-32b-instruct"],
        requires_key=True,
        env_key="DASHSCOPE_API_KEY",
        category="cloud",
        description="阿里云通义千问 OpenAI 兼容接口。",
    ),
    ProviderSpec(
        provider_id="siliconflow",
        name="硅基流动 (SiliconFlow)",
        base_url="https://api.siliconflow.cn/v1",
        default_model="deepseek-ai/DeepSeek-V3",
        models=[
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen2.5-7B-Instruct",
        ],
        requires_key=True,
        env_key="SILICONFLOW_API_KEY",
        category="cloud",
        description="硅基流动高速云端聚合推理服务。",
    ),
    ProviderSpec(
        provider_id="zhipu",
        name="智谱清言 (GLM-4)",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-flash",
        models=["glm-4-flash", "glm-4-plus", "glm-4-air"],
        requires_key=True,
        env_key="ZHIPU_API_KEY",
        category="cloud",
        description="智谱 AI OpenAI 兼容接口（含免费 glm-4-flash 模型）。",
    ),
    ProviderSpec(
        provider_id="moonshot",
        name="月之暗面 (Kimi / Moonshot)",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        requires_key=True,
        env_key="MOONSHOT_API_KEY",
        category="cloud",
        description="Kimi 长文本云端推理 API。",
    ),
    ProviderSpec(
        provider_id="openai",
        name="OpenAI (官方或通过 Resin 代理访问)",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        models=["gpt-4o-mini", "gpt-4o", "o3-mini"],
        requires_key=True,
        env_key="OPENAI_API_KEY",
        category="cloud",
        description="OpenAI 官方接口（亦可填写 Resin 反向代理 URL 测试粘性路由）。",
    ),
    ProviderSpec(
        provider_id="gemini",
        name="Google Gemini (OpenAI 兼容接口)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        models=["gemini-2.5-flash", "gemini-2.5-pro"],
        requires_key=True,
        env_key="GEMINI_API_KEY",
        category="cloud",
        description="Google Gemini 官方 OpenAI 兼容端点。",
    ),
    ProviderSpec(
        provider_id="anthropic",
        name="Anthropic Claude",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-3-7-sonnet-latest",
        models=["claude-3-7-sonnet-latest", "claude-3-5-haiku-latest"],
        requires_key=True,
        env_key="ANTHROPIC_API_KEY",
        category="cloud",
        description="Anthropic Claude Messages API / 兼容网关。",
    ),
    ProviderSpec(
        provider_id="openrouter",
        name="OpenRouter (全球模型聚合)",
        base_url="https://openrouter.ai/api/v1",
        default_model="deepseek/deepseek-chat",
        models=["deepseek/deepseek-chat", "google/gemini-2.5-flash", "anthropic/claude-3.7-sonnet"],
        requires_key=True,
        env_key="OPENROUTER_API_KEY",
        category="cloud",
        description="OpenRouter 统一多模型路由接口。",
    ),
    ProviderSpec(
        provider_id="custom",
        name="自定义 OpenAI 兼容接口 (或 Resin 反代网关)",
        base_url="http://127.0.0.1:2260/my-token/Default/https/api.openai.com/v1",
        default_model="gpt-4o-mini",
        models=["gpt-4o-mini", "deepseek-chat", "qwen-plus"],
        requires_key=False,
        env_key="CUSTOM_LLM_API_KEY",
        category="local",
        description="支持任意兼容 OpenAI /v1/chat/completions 的端点，也可直接填写 Resin 反向代理地址实现多 Key 粘性出口固定！",
    ),
]


class LLMProviderManager:
    """管理本地与云端大模型配置、持久化及推理请求."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        if config_dir is None:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
            config_dir = base / "Resin"
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "llm_config.json"
        self.providers: Dict[str, ProviderSpec] = {p.provider_id: p for p in BUILTIN_PROVIDERS}
        self.settings: Dict[str, Any] = {
            "active_provider": "ollama",
            "active_model": "qwen2.5:7b",
            "temperature": 0.3,
            "use_resin_proxy": False,
            "resin_proxy_url": "http://127.0.0.1:2260",
            "provider_configs": {},
        }
        self.load()

    def load(self) -> None:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.settings.update(data)
            except Exception:
                pass

        for pid, spec in self.providers.items():
            p_cfg = self.settings.setdefault("provider_configs", {}).setdefault(pid, {})
            p_cfg.setdefault("base_url", spec.base_url)
            p_cfg.setdefault("model", spec.default_model)
            if not p_cfg.get("api_key") and spec.env_key:
                p_cfg["api_key"] = os.environ.get(spec.env_key, "")

    def save(self) -> None:
        self.config_path.write_text(
            json.dumps(self.settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_providers(self) -> List[Dict[str, Any]]:
        result = []
        active_pid = self.settings.get("active_provider", "ollama")
        for pid, spec in self.providers.items():
            cfg = self.settings.get("provider_configs", {}).get(pid, {})
            d = asdict(spec)
            d["configured_base_url"] = cfg.get("base_url", spec.base_url)
            d["configured_model"] = cfg.get("model", spec.default_model)
            d["has_api_key"] = bool(cfg.get("api_key"))
            d["is_active"] = pid == active_pid
            result.append(d)
        return result

    def get_provider_config(self, provider_id: Optional[str] = None) -> Dict[str, Any]:
        pid = provider_id or self.settings.get("active_provider", "ollama")
        spec = self.providers.get(pid, BUILTIN_PROVIDERS[0])
        cfg = self.settings.get("provider_configs", {}).get(pid, {})
        return {
            "provider_id": spec.provider_id,
            "name": spec.name,
            "base_url": cfg.get("base_url") or spec.base_url,
            "model": cfg.get("model") or spec.default_model,
            "api_key": cfg.get("api_key", ""),
            "requires_key": spec.requires_key,
            "category": spec.category,
        }

    def update_provider_config(
        self,
        provider_id: str,
        base_url: str,
        model: str,
        api_key: str,
        set_active: bool = True,
    ) -> None:
        p_cfgs = self.settings.setdefault("provider_configs", {})
        p_cfgs[provider_id] = {
            "base_url": base_url.strip(),
            "model": model.strip(),
            "api_key": api_key.strip(),
        }
        if set_active:
            self.settings["active_provider"] = provider_id
            self.settings["active_model"] = model.strip()
        self.save()

    def probe_local_models(self, provider_id: Optional[str] = None) -> Dict[str, Any]:
        cfg = self.get_provider_config(provider_id)
        base_url = cfg["base_url"].rstrip("/")
        url = f"{base_url}/models"
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)",
            "Accept": "application/json",
        }
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"

        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=6) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                return {
                    "ok": True,
                    "latency_ms": round((time.time() - t0) * 1000, 1),
                    "models": models,
                    "message": f"连接成功 ({len(models)} 个可用模型)",
                }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "models": [],
                "message": f"连接失败: {exc}",
            }

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        cfg = self.get_provider_config(provider_id)
        target_model = model or cfg["model"]
        base_url = cfg["base_url"].rstrip("/")

        if cfg["requires_key"] and not cfg["api_key"]:
            return {
                "ok": False,
                "content": (
                    f"[{cfg['name']}] 尚未配置 API Key。请在「大模型与本地 API」面板中填入密钥，"
                    "或切换为本地免 Key 的 Ollama / LM Studio / vLLM 模型。\n\n"
                    + self._offline_expert_fallback(messages)
                ),
                "model": target_model,
                "provider": cfg["provider_id"],
            }

        url = f"{base_url}/chat/completions"
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)",
        }
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                return {
                    "ok": True,
                    "content": content,
                    "model": target_model,
                    "provider": cfg["provider_id"],
                    "raw": data,
                }
        except Exception as exc:
            return {
                "ok": False,
                "content": (
                    f"调用 {cfg['name']} ({url}) 遇到网络异常: {exc}\n\n"
                    "--- 已自动启用 Resin 内置离线专家引擎生成方案 ---\n\n"
                    + self._offline_expert_fallback(messages)
                ),
                "model": target_model,
                "provider": cfg["provider_id"],
            }

    @staticmethod
    def _offline_expert_fallback(messages: List[Dict[str, str]]) -> str:
        last_msg = messages[-1].get("content", "") if messages else ""
        if "正则" in last_msg or "筛选" in last_msg or "过滤" in last_msg or "Platform" in last_msg:
            return (
                "### Resin Platform 节点过滤规则建议\n\n"
                "1. **地区过滤 (`region_filters`)**：每行一个小写 ISO 国家代码，例如：\n"
                "```text\nhk\nsg\njp\nus\n```\n"
                "2. **节点标签正则过滤 (`regex_filters`)**：匹配 `<订阅名>/<节点名>`：\n"
                "   - 普通行为 `OR` 关系（命中任意一条即入选）\n"
                "   - `*` 开头表示 `AND` 必须命中\n"
                "   - `!` 开头表示 `NOT` 命中即排除\n"
                "```text\n(?i)(香港|HK|HongKong|新加坡|SG|日本|JP)\n*(?i)(专线|IEPL|IPLC|BGP|高速)\n!(?i)(过期|剩余|流量|官网|测试|倍率和?[2-9])\n```"
            )
        if "代码" in last_msg or "接入" in last_msg or "粘性" in last_msg:
            return (
                "### Resin 粘性代理业务代码快速接入模板 (Python)\n\n"
                "```python\n"
                "import requests\n\n"
                "# 方式 1：正向代理 (Platform.Account:ProxyToken)\n"
                "proxies = {\n"
                '    "http": "http://Default.user_001:my-token@127.0.0.1:2260",\n'
                '    "https": "http://Default.user_001:my-token@127.0.0.1:2260",\n'
                "}\n"
                'resp = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)\n'
                "print('当前绑定出口 IP:', resp.json())\n\n"
                "# 方式 2：反向代理 + X-Resin-Account 请求头（零侵入改 BaseURL）\n"
                'rev_url = "http://127.0.0.1:2260/my-token/Default/https/api.ipify.org?format=json"\n'
                'resp2 = requests.get(rev_url, headers={"X-Resin-Account": "user_001"}, timeout=10)\n'
                "print('反向代理出口 IP:', resp2.json())\n"
                "```"
            )
        return (
            "### Resin 智能网关诊断与优化建议\n\n"
            "- **节点熔断排查**：若节点 `circuit_open_since` 非空，说明连续失败次数达到 `max_consecutive_failures`（默认 3 次），可在「全局节点池」点击「探测延迟」与「探测出口 IP」立即尝试半开恢复，或在「订阅管理」点击「清理熔断节点」。\n"
            "- **粘性会话保持**：推荐使用反向代理配合 `X-Resin-Account` 请求头或「请求头提取规则」（自动识别 `Authorization` / `x-api-key`），为每个 API Key 绑定固定出口 IP。\n"
            "- **链式代理配置**：可将机场订阅设为「链式跳板 (`chain_relay`)」，将静态住宅 IP 订阅设为「链式落地 (`chain_proxy`)」，Resin 会使用 P2C 算法自动匹配最低延迟跳板。"
        )
