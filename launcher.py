"""Resin 智能代理池网关 v1.2.0 — 统一桌面运行时入口与 CI 自检启动器."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _configure_streams_and_paths() -> Path:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent

    for sub in ("", "desktop_gui", "scripts", "_internal"):
        candidate = (base_dir / sub).resolve()
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    os.environ["PYTHONPATH"] = os.pathsep.join(sys.path)
    return base_dir


def run_self_test(base_dir: Path) -> int:
    print("=== Resin v1.2.0 Desktop & Core Packaging Self-Test ===")
    try:
        import desktop_gui
        from desktop_gui.core_manager import AutoHealWatchdog, ResinAPIClient, ResinCoreProcessManager
        from desktop_gui.data_sources import DataSourceManager
        from desktop_gui.llm_providers import LLMProviderManager
        from desktop_gui.local_api_server import LocalGatewayHTTPServer
        from desktop_gui.updater import AutoUpdater
        import PySide6.QtCore
        import PySide6.QtGui
        import PySide6.QtWidgets
        from desktop_gui.gui_app import RealtimeLineChartWidget, ResinMainWindow

        print(f"[OK] Imported desktop_gui v{desktop_gui.__version__} and PySide6 ({PySide6.__version__})")

        llm_mgr = LLMProviderManager()
        providers = llm_mgr.list_providers()
        assert len(providers) >= 10, "Expected at least 10 built-in local/cloud LLM providers"
        fallback_resp = llm_mgr.chat_completion([{"role": "user", "content": "生成 Platform 正则过滤规则"}])
        assert "content" in fallback_resp and len(fallback_resp["content"]) > 20
        print(f"[OK] LLMProviderManager verified ({len(providers)} providers)")

        ds_mgr = DataSourceManager()
        sources = ds_mgr.list_sources()
        assert len(sources) >= 6, "Expected at least 6 data sources"
        print(f"[OK] DataSourceManager verified ({len(sources)} data sources)")

        core_mgr = ResinCoreProcessManager(app_dir=base_dir)
        env_cfg = core_mgr.ensure_default_env()
        assert "RESIN_ADMIN_TOKEN" in env_cfg and "RESIN_PROXY_TOKEN" in env_cfg
        core_bin = core_mgr.find_core_binary()
        if core_bin and core_bin.exists():
            res = subprocess.run(
                [str(core_bin), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            print(f"[OK] Bundled resin-core binary verified: {res.stdout.strip()}")
        else:
            print("[INFO] resin-core binary not in current test directory (checked during CI bundle stage)")

        api_client = ResinAPIClient()
        watchdog = AutoHealWatchdog(api_client=api_client, core_mgr=core_mgr)
        srv = LocalGatewayHTTPServer(
            llm_mgr=llm_mgr,
            ds_mgr=ds_mgr,
            core_mgr=core_mgr,
            api_client=api_client,
            watchdog=watchdog,
            port=0,
        )
        bound_port = srv.start()
        assert bound_port > 0, "LocalGatewayHTTPServer failed to bind port"
        srv.stop()
        print(f"[OK] LocalGatewayHTTPServer & AutoHealWatchdog verified on port {bound_port}")

        updater = AutoUpdater()
        assert updater.current_version == desktop_gui.__version__
        print("[OK] AutoUpdater initialized cleanly")
        print("=== SELF-TEST PASSED (EXIT 0) ===")
        return 0
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(f"[FAIL] Self-test failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    base_dir = _configure_streams_and_paths()
    parser = argparse.ArgumentParser(description="Resin 智能代理池网关桌面端启动器")
    parser.add_argument(
        "--mode",
        choices=["gui", "self-test", "api-only"],
        default="gui",
        help="运行模式: gui (默认启动中文桌面客户端), self-test (CI 模块完整性自检), api-only (仅后台 API 网关)",
    )
    parser.add_argument("--api-port", type=int, default=8787, help="本地 OpenAI 兼容 API 端口 (默认 8787)")
    parser.add_argument("--minimized", action="store_true", help="启动后自动最小化驻留到系统托盘 (用于开机自启)")
    args, _ = parser.parse_known_args()

    if args.mode == "self-test":
        return run_self_test(base_dir)

    from desktop_gui.core_manager import AutoHealWatchdog, ResinAPIClient, ResinCoreProcessManager
    from desktop_gui.data_sources import DataSourceManager
    from desktop_gui.llm_providers import LLMProviderManager
    from desktop_gui.local_api_server import LocalGatewayHTTPServer

    core_mgr = ResinCoreProcessManager(app_dir=base_dir)
    env_cfg = core_mgr.ensure_default_env()
    api_client = ResinAPIClient(
        base_url=f"http://127.0.0.1:{env_cfg.get('RESIN_PORT', '2260')}",
        admin_token=env_cfg.get("RESIN_ADMIN_TOKEN", "admin123"),
        proxy_token=env_cfg.get("RESIN_PROXY_TOKEN", "my-token"),
    )
    llm_mgr = LLMProviderManager()
    ds_mgr = DataSourceManager()
    watchdog = AutoHealWatchdog(api_client=api_client, core_mgr=core_mgr)

    local_srv = LocalGatewayHTTPServer(
        llm_mgr=llm_mgr,
        ds_mgr=ds_mgr,
        core_mgr=core_mgr,
        api_client=api_client,
        watchdog=watchdog,
        port=args.api_port,
    )
    actual_port = local_srv.start()

    if args.mode == "api-only":
        import time

        core_mgr.start()
        watchdog.start()
        print(f"Resin API-only mode running (Local LLM Gateway: http://127.0.0.1:{actual_port})")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            watchdog.stop()
            core_mgr.stop()
            local_srv.stop()
        return 0

    from desktop_gui.gui_app import launch_desktop_gui

    try:
        return launch_desktop_gui(
            core_mgr=core_mgr,
            api_client=api_client,
            llm_mgr=llm_mgr,
            ds_mgr=ds_mgr,
            watchdog=watchdog,
            local_api_port=actual_port,
            start_minimized=args.minimized,
        )
    finally:
        local_srv.stop()


if __name__ == "__main__":
    sys.exit(main())
