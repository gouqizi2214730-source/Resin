"""Resin 纯原生现代中文桌面端 GUI v1.2.0 (PySide6 / Qt 6, 含系统托盘常驻、开机自启、实时动态折线图与 AI 自动巡检自愈)."""

from __future__ import annotations

import collections
import ctypes
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, QObject
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __app_name__, __version__
from .core_manager import AutoHealWatchdog, ResinAPIClient, ResinCoreProcessManager
from .data_sources import DataSourceManager
from .llm_providers import LLMProviderManager
from .updater import AutoUpdater


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0F172A;
    color: #F1F5F9;
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #1E293B;
    background-color: #0F172A;
    border-radius: 8px;
}
QTabBar::tab {
    background-color: #1E293B;
    color: #94A3B8;
    padding: 9px 14px;
    margin-right: 4px;
    margin-bottom: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background-color: #0284C7;
    color: #FFFFFF;
}
QTabBar::tab:hover:!selected {
    background-color: #334155;
    color: #E2E8F0;
}
QGroupBox {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px;
    font-weight: bold;
    color: #38BDF8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QPushButton {
    background-color: #0284C7;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #0369A1;
}
QPushButton:pressed {
    background-color: #075985;
}
QPushButton[btnRole="success"] {
    background-color: #059669;
}
QPushButton[btnRole="success"]:hover {
    background-color: #047857;
}
QPushButton[btnRole="danger"] {
    background-color: #DC2626;
}
QPushButton[btnRole="danger"]:hover {
    background-color: #B91C1C;
}
QPushButton[btnRole="secondary"] {
    background-color: #334155;
    color: #E2E8F0;
}
QPushButton[btnRole="secondary"]:hover {
    background-color: #475569;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #0F172A;
    color: #F8FAFC;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 8px;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #38BDF8;
}
QTableWidget {
    background-color: #0F172A;
    alternate-background-color: #162032;
    color: #E2E8F0;
    border: 1px solid #334155;
    border-radius: 6px;
    gridline-color: #1E293B;
}
QHeaderView::section {
    background-color: #1E293B;
    color: #38BDF8;
    font-weight: bold;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #334155;
    border-bottom: 1px solid #334155;
}
QFrame[card="true"] {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px;
}
"""


class AsyncBridge(QObject):
    """跨线程 UI 安全回调桥接器."""

    done = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.done.connect(self._on_done)

    @staticmethod
    def _on_done(callback: Callable[[Any], None], result: Any) -> None:
        if callback:
            callback(result)

    def run_async(self, fn: Callable[[], Any], callback: Callable[[Any], None]) -> None:
        def worker() -> None:
            try:
                res = fn()
            except Exception as exc:
                res = (False, str(exc))
            self.done.emit(callback, res)

        threading.Thread(target=worker, daemon=True).start()


def enable_windows_hidpi_and_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Resin.ProxyGateway.Desktop.1.2")
    except Exception:
        pass


def resolve_app_icon_path() -> Optional[Path]:
    base_dirs = []
    if getattr(sys, "frozen", False):
        base_dirs.append(Path(sys.executable).resolve().parent)
        if hasattr(sys, "_MEIPASS"):
            base_dirs.append(Path(getattr(sys, "_MEIPASS")))
    base_dirs.append(Path(__file__).resolve().parent.parent)

    for b in base_dirs:
        for rel in ("assets/resin.ico", "resin.ico", "_internal/assets/resin.ico"):
            p = b / rel
            if p.exists():
                return p
    return None


class RealtimeLineChartWidget(QWidget):
    """硬件加速 QPainter 实时双序列动态折线图组件 (带渐变面积填充与网格坐标)."""

    def __init__(
        self,
        title: str = "实时吞吐速率趋势 (KB/s)",
        series1_name: str = "下行速率 (Egress)",
        series2_name: str = "上行速率 (Ingress)",
        color1: str = "#38BDF8",
        color2: str = "#10B981",
        unit: str = "KB/s",
        max_points: int = 45,
    ) -> None:
        super().__init__()
        self.title = title
        self.series1_name = series1_name
        self.series2_name = series2_name
        self.color1 = QColor(color1)
        self.color2 = QColor(color2)
        self.unit = unit
        self.max_points = max_points
        self.series1: Deque[float] = collections.deque([0.0] * 15, maxlen=max_points)
        self.series2: Deque[float] = collections.deque([0.0] * 15, maxlen=max_points)
        self.setMinimumHeight(185)

    def push_sample(self, v1: float, v2: float) -> None:
        self.series1.append(max(0.0, float(v1)))
        self.series2.append(max(0.0, float(v2)))
        self.update()

    def set_series(self, s1: List[float], s2: List[float]) -> None:
        self.series1.clear()
        self.series2.clear()
        for v in s1[-self.max_points :]:
            self.series1.append(max(0.0, float(v)))
        for v in s2[-self.max_points :]:
            self.series2.append(max(0.0, float(v)))
        while len(self.series1) < 2:
            self.series1.append(0.0)
        while len(self.series2) < 2:
            self.series2.append(0.0)
        self.update()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, QColor("#0F172A"))
        border_pen = QPen(QColor("#334155"), 1)
        painter.setPen(border_pen)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)

        # Header & Legend
        painter.setPen(QColor("#E2E8F0"))
        painter.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        painter.drawText(14, 22, self.title)

        cur1 = self.series1[-1] if self.series1 else 0.0
        cur2 = self.series2[-1] if self.series2 else 0.0
        legend_text = f"● {self.series1_name}: {cur1:.1f} {self.unit}    ● {self.series2_name}: {cur2:.1f} {self.unit}"
        painter.setFont(QFont("Microsoft YaHei", 8))
        painter.setPen(self.color1)
        painter.drawText(rect.width() - 360, 22, legend_text)

        plot = QRectF(46, 34, max(40, rect.width() - 60), max(40, rect.height() - 50))
        max_val = max(
            max(self.series1) if self.series1 else 1.0,
            max(self.series2) if self.series2 else 1.0,
            10.0,
        ) * 1.15

        # Draw grid lines
        grid_pen = QPen(QColor("#1E293B"), 1, Qt.DashLine)
        label_pen = QPen(QColor("#64748B"), 1)
        for i in range(4):
            y = plot.top() + plot.height() * i / 3.0
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            val = max_val * (1.0 - i / 3.0)
            painter.setPen(label_pen)
            painter.drawText(4, int(y + 4), f"{val:.0f}")

        self._draw_curve(painter, plot, list(self.series1), max_val, self.color1)
        self._draw_curve(painter, plot, list(self.series2), max_val, self.color2)
        painter.end()

    @staticmethod
    def _draw_curve(
        painter: QPainter,
        plot: QRectF,
        values: List[float],
        max_val: float,
        color: QColor,
    ) -> None:
        if len(values) < 2:
            return
        n = len(values)
        pts: List[QPointF] = []
        for idx, v in enumerate(values):
            x = plot.left() + plot.width() * idx / (n - 1)
            y = plot.bottom() - (min(v, max_val) / max_val) * plot.height()
            pts.append(QPointF(x, y))

        path = QPainterPath()
        path.moveTo(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)

        fill_path = QPainterPath(path)
        fill_path.lineTo(QPointF(pts[-1].x(), plot.bottom()))
        fill_path.lineTo(QPointF(pts[0].x(), plot.bottom()))
        fill_path.closeSubpath()

        grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
        c_top = QColor(color)
        c_top.setAlpha(75)
        c_bot = QColor(color)
        c_bot.setAlpha(4)
        grad.setColorAt(0.0, c_top)
        grad.setColorAt(1.0, c_bot)
        painter.fillPath(fill_path, QBrush(grad))

        line_pen = QPen(color, 2.2)
        painter.setPen(line_pen)
        painter.drawPath(path)


class MetricCard(QFrame):
    """顶部指标展示卡片."""

    def __init__(self, title: str, initial: str = "0", subtitle: str = "") -> None:
        super().__init__()
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 600;")
        self.lbl_value = QLabel(initial)
        self.lbl_value.setStyleSheet("color: #38BDF8; font-size: 22px; font-weight: bold;")
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setStyleSheet("color: #64748B; font-size: 11px;")
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        layout.addWidget(self.lbl_sub)

    def set_value(self, val: str, sub: Optional[str] = None, color: str = "#38BDF8") -> None:
        self.lbl_value.setText(val)
        self.lbl_value.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")
        if sub is not None:
            self.lbl_sub.setText(sub)


class ResinMainWindow(QMainWindow):
    """Resin 智能代理池网关 v1.2.0 — 中文现代桌面端主窗口."""

    def __init__(
        self,
        core_mgr: Optional[ResinCoreProcessManager] = None,
        api_client: Optional[ResinAPIClient] = None,
        llm_mgr: Optional[LLMProviderManager] = None,
        ds_mgr: Optional[DataSourceManager] = None,
        watchdog: Optional[AutoHealWatchdog] = None,
        local_api_port: int = 8787,
    ) -> None:
        super().__init__()
        self.bridge = AsyncBridge()
        self.core_mgr = core_mgr or ResinCoreProcessManager()
        env_cfg = self.core_mgr.ensure_default_env()
        port = env_cfg.get("RESIN_PORT", "2260")
        admin_token = env_cfg.get("RESIN_ADMIN_TOKEN", "admin123")
        proxy_token = env_cfg.get("RESIN_PROXY_TOKEN", "my-token")

        self.api = api_client or ResinAPIClient(
            base_url=f"http://127.0.0.1:{port}",
            admin_token=admin_token,
            proxy_token=proxy_token,
        )
        self.llm_mgr = llm_mgr or LLMProviderManager()
        self.ds_mgr = ds_mgr or DataSourceManager()
        self.watchdog = watchdog or AutoHealWatchdog(self.api, self.core_mgr)
        self.watchdog.start()
        self.updater = AutoUpdater()
        self.local_api_port = local_api_port
        self._force_quit = False

        self.setWindowTitle(f"{__app_name__} v{__version__} — 高性能粘性会话代理池网关控制台")
        self.resize(1380, 880)
        self._apply_window_icon()
        self._setup_system_tray()

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # 顶部快捷控制栏
        root_layout.addWidget(self._build_top_bar(env_cfg))

        # 主功能标签页 (11 个完整模块)
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_dashboard_tab(), "🚀 网关总览与实时图表")
        self.tabs.addTab(self._build_subscriptions_tab(), "📡 订阅源管理")
        self.tabs.addTab(self._build_platforms_tab(), "🎯 平台与粘性隔离池")
        self.tabs.addTab(self._build_nodes_tab(), "🌐 全局节点池与探测")
        self.tabs.addTab(self._build_leases_tab(), "🔗 粘性租约与 IP 负载")
        self.tabs.addTab(self._build_endpoints_tester_tab(), "🔌 多接入点与代理测试")
        self.tabs.addTab(self._build_rules_tab(), "📑 请求头账号提取规则")
        self.tabs.addTab(self._build_request_logs_tab(), "📜 结构化请求日志")
        self.tabs.addTab(self._build_geoip_sysconfig_tab(), "🌍 GeoIP 与系统配置")
        self.tabs.addTab(self._build_datasources_tab(), "🗄️ 数据源 API 中心")
        self.tabs.addTab(self._build_llm_updater_tab(), "🤖 大模型自愈与更新")

        # 底部状态栏
        self.status_bar = self.statusBar()
        self.status_bar.showMessage(
            f"就绪 | Resin 控制面: {self.api.base_url} | 本地 OpenAI 兼容网关: http://127.0.0.1:{self.local_api_port} | 关闭窗口将自动最小化至系统托盘"
        )

        # 定时刷新器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._periodic_tick)
        self.timer.start(3500)

        # 自动尝试启动内置 resin-core 引擎
        QTimer.singleShot(300, self._auto_start_core_on_launch)

    def _apply_window_icon(self) -> None:
        ico_path = resolve_app_icon_path()
        if not ico_path:
            return
        icon = QIcon(str(ico_path))
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app:
            app.setWindowIcon(icon)
        if sys.platform == "win32":
            try:
                hwnd = int(self.winId())
                WM_SETICON = 0x0080
                IMAGE_ICON = 1
                LR_LOADFROMFILE = 0x00000010
                hicon_big = ctypes.windll.user32.LoadImageW(
                    0, str(ico_path), IMAGE_ICON, 256, 256, LR_LOADFROMFILE
                )
                hicon_small = ctypes.windll.user32.LoadImageW(
                    0, str(ico_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE
                )
                if hicon_big:
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon_big)
                if hicon_small:
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon_small)
            except Exception:
                pass

    def _setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        ico_path = resolve_app_icon_path()
        icon = QIcon(str(ico_path)) if ico_path else self.windowIcon()
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(f"{__app_name__} v{__version__} (后台常驻运行中)")

        menu = QMenu(self)
        act_show = QAction("🖥 显示 Resin 主控制台", self)
        act_show.triggered.connect(self._restore_from_tray)
        menu.addAction(act_show)

        act_restart = QAction("▶ 启动 / 重启本地网关引擎", self)
        act_restart.triggered.connect(self._on_restart_core)
        menu.addAction(act_restart)

        act_heal = QAction("🩺 立即执行 AI 节点池巡检与自愈", self)
        act_heal.triggered.connect(self._trigger_manual_auto_heal)
        menu.addAction(act_heal)

        menu.addSeparator()
        act_proxy_on = QAction("⚡ 开启 Windows 系统代理", self)
        act_proxy_on.triggered.connect(lambda: self._toggle_windows_proxy(True))
        menu.addAction(act_proxy_on)

        act_proxy_off = QAction("关闭 Windows 系统代理", self)
        act_proxy_off.triggered.connect(lambda: self._toggle_windows_proxy(False))
        menu.addAction(act_proxy_off)

        menu.addSeparator()
        act_quit = QAction("🚪 彻底退出并停止网关", self)
        act_quit.triggered.connect(self.quit_completely)
        menu.addAction(act_quit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def quit_completely(self) -> None:
        self._force_quit = True
        self.watchdog.stop()
        if self.core_mgr.is_running():
            self.core_mgr.stop()
        if getattr(self, "tray_icon", None):
            self.tray_icon.hide()
        QApplication.quit()

    def _build_top_bar(self, env_cfg: Dict[str, str]) -> QFrame:
        bar = QFrame()
        bar.setProperty("card", True)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)

        title_lbl = QLabel(f"🛡️ {__app_name__} v{__version__}")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        layout.addWidget(title_lbl)

        self.lbl_core_badge = QLabel("● 本地引擎: 检测中")
        self.lbl_core_badge.setStyleSheet("color: #F59E0B; font-weight: bold; margin-left: 8px;")
        layout.addWidget(self.lbl_core_badge)

        layout.addSpacing(8)
        layout.addWidget(QLabel("网关:"))
        self.inp_base_url = QLineEdit(self.api.base_url)
        self.inp_base_url.setFixedWidth(165)
        layout.addWidget(self.inp_base_url)

        layout.addWidget(QLabel("管理密码:"))
        self.inp_admin_token = QLineEdit(self.api.admin_token)
        self.inp_admin_token.setEchoMode(QLineEdit.Password)
        self.inp_admin_token.setFixedWidth(95)
        layout.addWidget(self.inp_admin_token)

        layout.addWidget(QLabel("代理密码:"))
        self.inp_proxy_token = QLineEdit(self.api.proxy_token)
        self.inp_proxy_token.setEchoMode(QLineEdit.Password)
        self.inp_proxy_token.setFixedWidth(95)
        layout.addWidget(self.inp_proxy_token)

        btn_connect = QPushButton("刷新全局")
        btn_connect.clicked.connect(self.refresh_all_views)
        layout.addWidget(btn_connect)

        btn_start_core = QPushButton("▶ 启动引擎")
        btn_start_core.setProperty("btnRole", "success")
        btn_start_core.clicked.connect(self._on_start_core)
        layout.addWidget(btn_start_core)

        btn_stop_core = QPushButton("■ 停止")
        btn_stop_core.setProperty("btnRole", "danger")
        btn_stop_core.clicked.connect(self._on_stop_core)
        layout.addWidget(btn_stop_core)

        self.chk_startup = QCheckBox("开机自启")
        self.chk_startup.setChecked(self.core_mgr.is_windows_startup_enabled())
        self.chk_startup.toggled.connect(self._on_toggle_windows_startup)
        layout.addWidget(self.chk_startup)

        self.chk_auto_heal = QCheckBox("AI 自动巡检自愈")
        self.chk_auto_heal.setChecked(True)
        self.chk_auto_heal.toggled.connect(self._on_toggle_auto_heal)
        layout.addWidget(self.chk_auto_heal)

        btn_webui = QPushButton("🌐 WebUI")
        btn_webui.setProperty("btnRole", "secondary")
        btn_webui.clicked.connect(lambda: webbrowser.open(self.api.base_url))
        layout.addWidget(btn_webui)

        return bar

    def _on_toggle_windows_startup(self, checked: bool) -> None:
        ok, msg = self.core_mgr.set_windows_startup(checked)
        self.status_bar.showMessage(msg)

    def _on_toggle_auto_heal(self, checked: bool) -> None:
        self.watchdog.enabled = checked
        state = "已启用 AI 定时巡检与节点池自愈" if checked else "已暂停 AI 定时巡检自愈"
        self.status_bar.showMessage(state)

    def _trigger_manual_auto_heal(self) -> None:
        self.status_bar.showMessage("🩺 正在执行 AI 节点池健康巡检与熔断自愈...")
        self.bridge.run_async(
            self.watchdog.run_patrol_once,
            lambda r: (
                self.status_bar.showMessage(r.get("summary", "巡检完成") if isinstance(r, dict) else str(r)),
                self.refresh_all_views(),
            ),
        )

    # =========================================================================
    # Tab 1: 网关总览与实时动态图表监控
    # =========================================================================
    def _build_dashboard_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        cards_grid = QGridLayout()
        self.card_total_nodes = MetricCard("全局总节点数", "0", "跨订阅自动去重")
        self.card_healthy_nodes = MetricCard("健康可用节点", "0", "出站就绪且未熔断")
        self.card_egress_ips = MetricCard("独立出口 IP 总数", "0", "健康独立 IP: 0")
        self.card_throughput = MetricCard("实时吞吐速率", "0 B/s", "上行 / 下行实时带宽")
        self.card_connections = MetricCard("活跃并发连接", "0", "入站 / 出站活动连接")
        self.card_leases = MetricCard("活跃粘性租约", "0", "Account -> 固定出口 IP")

        cards_grid.addWidget(self.card_total_nodes, 0, 0)
        cards_grid.addWidget(self.card_healthy_nodes, 0, 1)
        cards_grid.addWidget(self.card_egress_ips, 0, 2)
        cards_grid.addWidget(self.card_throughput, 0, 3)
        cards_grid.addWidget(self.card_connections, 0, 4)
        cards_grid.addWidget(self.card_leases, 0, 5)
        layout.addLayout(cards_grid)

        # 中部：双实时动态曲线图表 (吞吐速率折线图 + 并发连接与粘性租约折线图)
        charts_row = QHBoxLayout()
        self.chart_throughput = RealtimeLineChartWidget(
            title="📈 实时网络吞吐速率监控曲线 (KB/s)",
            series1_name="下行吞吐 (Egress)",
            series2_name="上行吞吐 (Ingress)",
            color1="#38BDF8",
            color2="#10B981",
            unit="KB/s",
        )
        self.chart_conns_leases = RealtimeLineChartWidget(
            title="🔗 实时并发连接数与活跃粘性租约趋势",
            series1_name="并发连接数 (Conns)",
            series2_name="活跃粘性租约 (Leases)",
            color1="#F59E0B",
            color2="#A855F7",
            unit="",
        )
        charts_row.addWidget(self.chart_throughput, 1)
        charts_row.addWidget(self.chart_conns_leases, 1)
        layout.addLayout(charts_row)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧：权威域名节点延迟分布 & 系统信息
        left_box = QGroupBox("节点权威延迟分布直方图 & 系统运行状态")
        left_lay = QVBoxLayout(left_box)
        self.lbl_sys_info = QLabel("Resin 版本信息: 等待连接...")
        self.lbl_sys_info.setStyleSheet("color: #94A3B8;")
        left_lay.addWidget(self.lbl_sys_info)

        self.tbl_latency_hist = QTableWidget(0, 3)
        self.tbl_latency_hist.setHorizontalHeaderLabels(["延迟区间 (ms)", "节点数量", "占比可视化"])
        self.tbl_latency_hist.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        left_lay.addWidget(self.tbl_latency_hist)

        sys_proxy_row = QHBoxLayout()
        btn_sys_on = QPushButton("⚡ 一键设为 Windows 系统代理")
        btn_sys_on.setProperty("btnRole", "success")
        btn_sys_on.clicked.connect(lambda: self._toggle_windows_proxy(True))
        btn_sys_off = QPushButton("关闭 Windows 系统代理")
        btn_sys_off.setProperty("btnRole", "secondary")
        btn_sys_off.clicked.connect(lambda: self._toggle_windows_proxy(False))
        btn_ai_heal = QPushButton("🩺 立即执行 AI 巡检自愈")
        btn_ai_heal.clicked.connect(self._trigger_manual_auto_heal)
        sys_proxy_row.addWidget(btn_sys_on)
        sys_proxy_row.addWidget(btn_sys_off)
        sys_proxy_row.addWidget(btn_ai_heal)
        left_lay.addLayout(sys_proxy_row)
        splitter.addWidget(left_box)

        # 右侧：本地 resin-core 实时控制台日志 & 快捷接入命令
        right_box = QGroupBox("本地 Resin 引擎与 AI 自愈实时日志 & 快速接入")
        right_lay = QVBoxLayout(right_box)
        self.txt_core_logs = QPlainTextEdit()
        self.txt_core_logs.setReadOnly(True)
        self.txt_core_logs.setPlaceholderText("本地 resin-core 核心引擎与 AI 自动巡检自愈日志将在此处实时滚动显示...")
        right_lay.addWidget(self.txt_core_logs)

        quick_row = QHBoxLayout()
        btn_copy_http = QPushButton("复制 HTTP 正向代理地址")
        btn_copy_http.clicked.connect(self._copy_http_proxy_cmd)
        btn_copy_socks = QPushButton("复制 SOCKS5 代理地址")
        btn_copy_socks.clicked.connect(self._copy_socks_proxy_cmd)
        btn_hide_tray = QPushButton("📥 最小化到系统托盘")
        btn_hide_tray.setProperty("btnRole", "secondary")
        btn_hide_tray.clicked.connect(self.hide)
        quick_row.addWidget(btn_copy_http)
        quick_row.addWidget(btn_copy_socks)
        quick_row.addWidget(btn_hide_tray)
        right_lay.addLayout(quick_row)
        splitter.addWidget(right_box)

        layout.addWidget(splitter, 1)
        return w

    # =========================================================================
    # Tab 2: 订阅源管理 (Subscriptions)
    # =========================================================================
    def _build_subscriptions_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left_box = QGroupBox("代理节点订阅源列表 (支持 Sing-box / Clash / URI / Base64 / HTTP 行)")
        left_lay = QVBoxLayout(left_box)

        filter_row = QHBoxLayout()
        self.inp_sub_keyword = QLineEdit()
        self.inp_sub_keyword.setPlaceholderText("输入订阅名称或 URL 关键词筛选...")
        btn_sub_query = QPushButton("查询订阅")
        btn_sub_query.clicked.connect(self.load_subscriptions)
        btn_sub_refresh_sel = QPushButton("🔄 立即刷新选中订阅")
        btn_sub_refresh_sel.setProperty("btnRole", "success")
        btn_sub_refresh_sel.clicked.connect(self._refresh_selected_subscription)
        btn_sub_clean_sel = QPushButton("🧹 清理熔断故障节点")
        btn_sub_clean_sel.setProperty("btnRole", "secondary")
        btn_sub_clean_sel.clicked.connect(self._cleanup_selected_subscription)
        btn_sub_del = QPushButton("🗑 删除选中订阅")
        btn_sub_del.setProperty("btnRole", "danger")
        btn_sub_del.clicked.connect(self._delete_selected_subscription)

        filter_row.addWidget(self.inp_sub_keyword, 1)
        filter_row.addWidget(btn_sub_query)
        filter_row.addWidget(btn_sub_refresh_sel)
        filter_row.addWidget(btn_sub_clean_sel)
        filter_row.addWidget(btn_sub_del)
        left_lay.addLayout(filter_row)

        self.tbl_subs = QTableWidget(0, 8)
        self.tbl_subs.setHorizontalHeaderLabels(
            ["ID", "订阅名称", "来源类型", "总节点 / 健康", "更新间隔", "链式角色", "状态", "地址 / 错误信息"]
        )
        self.tbl_subs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_subs.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_subs.itemSelectionChanged.connect(self._on_subscription_row_selected)
        left_lay.addWidget(self.tbl_subs)
        layout.addWidget(left_box, 3)

        right_box = QGroupBox("新建 / 编辑代理订阅源")
        form = QFormLayout(right_box)

        self.inp_sub_id = QLineEdit()
        self.inp_sub_id.setPlaceholderText("新建时留空；点击左侧行自动填入以编辑")
        self.inp_sub_id.setReadOnly(True)
        self.inp_sub_name = QLineEdit()
        self.inp_sub_name.setPlaceholderText("例如：主力专线订阅 / 静态住宅池")

        self.cmb_sub_type = QComboBox()
        self.cmb_sub_type.addItems(["remote (远程订阅 URL)", "local (本地直接粘贴节点内容)"])

        self.inp_sub_url = QLineEdit()
        self.inp_sub_url.setPlaceholderText("https://example.com/api/v1/client/subscribe?token=...")

        self.txt_sub_content = QPlainTextEdit()
        self.txt_sub_content.setPlaceholderText(
            "当选择 local 本地订阅时，在此直接粘贴节点 URI 列表、IP:PORT:USER:PASS、Clash YAML 或 Sing-box JSON..."
        )
        self.txt_sub_content.setFixedHeight(110)

        self.inp_sub_interval = QLineEdit("30m")
        self.inp_sub_evict_delay = QLineEdit("72h")
        self.chk_sub_enabled = QCheckBox("启用该订阅源")
        self.chk_sub_enabled.setChecked(True)
        self.chk_sub_ephemeral = QCheckBox("临时节点订阅 (Ephemeral 自动清理失效节点)")
        self.chk_sub_incremental = QCheckBox("增量保留存活节点 (刷新时不移除仍健康的旧节点)")

        self.cmb_sub_chain = QComboBox()
        self.cmb_sub_chain.addItems(
            ["普通直出节点 (默认)", "链式落地节点 (chain_proxy: 需经跳板中转)", "链式跳板节点 (chain_relay: 为落地节点提供中转)"]
        )

        form.addRow("订阅 ID:", self.inp_sub_id)
        form.addRow("订阅名称*:", self.inp_sub_name)
        form.addRow("来源类型*:", self.cmb_sub_type)
        form.addRow("远程 URL:", self.inp_sub_url)
        form.addRow("本地节点内容:", self.txt_sub_content)
        form.addRow("自动更新间隔:", self.inp_sub_interval)
        form.addRow("临时节点驱逐延迟:", self.inp_sub_evict_delay)
        form.addRow("链式代理角色:", self.cmb_sub_chain)
        form.addRow("", self.chk_sub_enabled)
        form.addRow("", self.chk_sub_ephemeral)
        form.addRow("", self.chk_sub_incremental)

        btn_row = QHBoxLayout()
        btn_create_sub = QPushButton("➕ 创建新订阅")
        btn_create_sub.setProperty("btnRole", "success")
        btn_create_sub.clicked.connect(self._create_subscription)
        btn_update_sub = QPushButton("💾 保存修改到选中订阅")
        btn_update_sub.clicked.connect(self._update_subscription)
        btn_row.addWidget(btn_create_sub)
        btn_row.addWidget(btn_update_sub)
        form.addRow(btn_row)

        layout.addWidget(right_box, 2)
        return w

    # =========================================================================
    # Tab 3: 平台与粘性隔离池 (Platforms)
    # =========================================================================
    def _build_platforms_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left_box = QGroupBox("Platform 节点隔离池列表 (按业务/地区/正则构建专属代理池)")
        left_lay = QVBoxLayout(left_box)

        act_row = QHBoxLayout()
        btn_plat_reload = QPushButton("刷新平台列表")
        btn_plat_reload.clicked.connect(self.load_platforms)
        btn_plat_rebuild = QPushButton("🔄 重建可路由视图")
        btn_plat_rebuild.setProperty("btnRole", "secondary")
        btn_plat_rebuild.clicked.connect(self._rebuild_selected_platform)
        btn_plat_reset = QPushButton("⏮ 重置为默认参数")
        btn_plat_reset.setProperty("btnRole", "secondary")
        btn_plat_reset.clicked.connect(self._reset_selected_platform)
        btn_plat_del = QPushButton("🗑 删除选中平台")
        btn_plat_del.setProperty("btnRole", "danger")
        btn_plat_del.clicked.connect(self._delete_selected_platform)

        act_row.addWidget(btn_plat_reload)
        act_row.addWidget(btn_plat_rebuild)
        act_row.addWidget(btn_plat_reset)
        act_row.addWidget(btn_plat_del)
        left_lay.addLayout(act_row)

        self.tbl_platforms = QTableWidget(0, 7)
        self.tbl_platforms.setHorizontalHeaderLabels(
            ["ID", "平台名称", "可路由节点数", "粘性 TTL", "分配策略", "地区过滤", "标签正则过滤"]
        )
        self.tbl_platforms.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_platforms.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_platforms.itemSelectionChanged.connect(self._on_platform_row_selected)
        left_lay.addWidget(self.tbl_platforms)

        self.txt_plat_preview = QPlainTextEdit()
        self.txt_plat_preview.setReadOnly(True)
        self.txt_plat_preview.setFixedHeight(140)
        self.txt_plat_preview.setPlaceholderText("点击右侧「预览过滤匹配节点」后，将在此展示命中的节点清单...")
        left_lay.addWidget(self.txt_plat_preview)
        layout.addWidget(left_box, 3)

        right_box = QGroupBox("新建 / 编辑 Platform 隔离池策略")
        form = QFormLayout(right_box)

        self.inp_plat_id = QLineEdit()
        self.inp_plat_id.setReadOnly(True)
        self.inp_plat_name = QLineEdit()
        self.inp_plat_name.setPlaceholderText("例如：US_AI_Pool 或 HK_LowLatency")
        self.inp_plat_ttl = QLineEdit("168h")

        self.cmb_plat_policy = QComboBox()
        self.cmb_plat_policy.addItems(["BALANCED", "PREFER_LOW_LATENCY", "PREFER_IDLE_IP"])

        self.cmb_plat_miss = QComboBox()
        self.cmb_plat_miss.addItems(["TREAT_AS_EMPTY", "REJECT"])

        self.cmb_plat_empty_acc = QComboBox()
        self.cmb_plat_empty_acc.addItems(["ACCOUNT_HEADER_RULE", "FIXED_HEADER", "RANDOM"])

        self.inp_plat_fixed_hdr = QLineEdit("Authorization")

        self.txt_plat_regions = QPlainTextEdit()
        self.txt_plat_regions.setPlaceholderText("每行一个小写国家/地区代码，例如：\nus\nhk\njp\nsg")
        self.txt_plat_regions.setFixedHeight(75)

        self.txt_plat_regex = QPlainTextEdit()
        self.txt_plat_regex.setPlaceholderText("每行一条 Go 正则表达式（*开头表示必须命中，!开头表示排除）：\n香港|日本|美国\n*专线\n!过期")
        self.txt_plat_regex.setFixedHeight(90)

        self.chk_plat_disable_cb = QCheckBox("禁用被动熔断 (Passive Circuit Breaker Disabled)")

        form.addRow("平台 ID:", self.inp_plat_id)
        form.addRow("平台名称*:", self.inp_plat_name)
        form.addRow("粘性会话 TTL:", self.inp_plat_ttl)
        form.addRow("节点分配策略:", self.cmb_plat_policy)
        form.addRow("反代未命中行为:", self.cmb_plat_miss)
        form.addRow("空账号提取行为:", self.cmb_plat_empty_acc)
        form.addRow("指定提取 Header:", self.inp_plat_fixed_hdr)
        form.addRow("地区过滤规则:", self.txt_plat_regions)
        form.addRow("标签正则规则:", self.txt_plat_regex)
        form.addRow("", self.chk_plat_disable_cb)

        btn_row = QHBoxLayout()
        btn_preview = QPushButton("🔍 预览过滤匹配节点")
        btn_preview.setProperty("btnRole", "secondary")
        btn_preview.clicked.connect(self._preview_platform_filter)
        btn_create_plat = QPushButton("➕ 创建新平台")
        btn_create_plat.setProperty("btnRole", "success")
        btn_create_plat.clicked.connect(self._create_platform)
        btn_update_plat = QPushButton("💾 更新选中平台")
        btn_update_plat.clicked.connect(self._update_platform)
        btn_row.addWidget(btn_preview)
        btn_row.addWidget(btn_create_plat)
        btn_row.addWidget(btn_update_plat)
        form.addRow(btn_row)

        layout.addWidget(right_box, 2)
        return w

    # =========================================================================
    # Tab 4: 全局节点池与主动探测 (Nodes & Active Probing)
    # =========================================================================
    def _build_nodes_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        filter_box = QGroupBox("多维度节点检索与主动探测控制")
        f_lay = QHBoxLayout(filter_box)

        self.inp_node_tag = QLineEdit()
        self.inp_node_tag.setPlaceholderText("节点标签关键字...")
        self.inp_node_region = QLineEdit()
        self.inp_node_region.setPlaceholderText("地区 (如 hk, us, jp)...")
        self.inp_node_region.setFixedWidth(120)
        self.inp_node_ip = QLineEdit()
        self.inp_node_ip.setPlaceholderText("出口 IP...")
        self.inp_node_ip.setFixedWidth(135)

        self.cmb_node_circuit = QComboBox()
        self.cmb_node_circuit.addItems(["全部熔断状态", "正常节点 (circuit_open=false)", "已熔断节点 (circuit_open=true)"])

        btn_query_nodes = QPushButton("🔍 检索节点池")
        btn_query_nodes.clicked.connect(self.load_nodes)
        btn_probe_egress = QPushButton("🌍 探测选中节点出口 IP")
        btn_probe_egress.setProperty("btnRole", "success")
        btn_probe_egress.clicked.connect(self._probe_selected_node_egress)
        btn_probe_lat = QPushButton("⚡ 探测选中节点权威延迟")
        btn_probe_lat.clicked.connect(self._probe_selected_node_latency)

        f_lay.addWidget(QLabel("标签:"))
        f_lay.addWidget(self.inp_node_tag, 1)
        f_lay.addWidget(QLabel("地区:"))
        f_lay.addWidget(self.inp_node_region)
        f_lay.addWidget(QLabel("出口 IP:"))
        f_lay.addWidget(self.inp_node_ip)
        f_lay.addWidget(self.cmb_node_circuit)
        f_lay.addWidget(btn_query_nodes)
        f_lay.addWidget(btn_probe_egress)
        f_lay.addWidget(btn_probe_lat)
        layout.addWidget(filter_box)

        self.tbl_nodes = QTableWidget(0, 8)
        self.tbl_nodes.setHorizontalHeaderLabels(
            ["节点 Hash", "显示标签 (订阅/节点)", "地区", "出口 IP", "参考延迟 (ms)", "失败次数", "健康/熔断状态", "链式角色 / 最近错误"]
        )
        self.tbl_nodes.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_nodes.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.tbl_nodes, 1)

        self.lbl_nodes_summary = QLabel("节点池统计: 等待加载...")
        self.lbl_nodes_summary.setStyleSheet("color: #38BDF8; font-weight: bold;")
        layout.addWidget(self.lbl_nodes_summary)
        return w

    # =========================================================================
    # Tab 5: 粘性租约与出口 IP 负载 (Sticky Leases & IP Load)
    # =========================================================================
    def _build_leases_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        top_box = QGroupBox("粘性会话租约管理与子账号租约继承")
        t_lay = QHBoxLayout(top_box)

        t_lay.addWidget(QLabel("选择平台:"))
        self.cmb_lease_platform = QComboBox()
        self.cmb_lease_platform.setMinimumWidth(180)
        self.cmb_lease_platform.currentIndexChanged.connect(lambda _: self.load_leases_and_ip_load())
        t_lay.addWidget(self.cmb_lease_platform)

        self.inp_lease_account = QLineEdit()
        self.inp_lease_account.setPlaceholderText("按业务 Account 筛选...")
        t_lay.addWidget(self.inp_lease_account)

        btn_load_leases = QPushButton("查询租约与负载")
        btn_load_leases.clicked.connect(self.load_leases_and_ip_load)
        btn_del_lease = QPushButton("释放选中账号租约")
        btn_del_lease.setProperty("btnRole", "secondary")
        btn_del_lease.clicked.connect(self._delete_selected_lease)
        btn_clear_leases = QPushButton("🗑 清空该平台全部租约")
        btn_clear_leases.setProperty("btnRole", "danger")
        btn_clear_leases.clicked.connect(self._clear_all_platform_leases)

        t_lay.addWidget(btn_load_leases)
        t_lay.addWidget(btn_del_lease)
        t_lay.addWidget(btn_clear_leases)

        t_lay.addSpacing(15)
        self.inp_parent_acc = QLineEdit()
        self.inp_parent_acc.setPlaceholderText("父账号 (Parent Account)")
        self.inp_new_acc = QLineEdit()
        self.inp_new_acc.setPlaceholderText("新子账号 (New Account)")
        btn_inherit = QPushButton("🧬 执行租约继承")
        btn_inherit.setProperty("btnRole", "success")
        btn_inherit.clicked.connect(self._on_inherit_lease)
        t_lay.addWidget(self.inp_parent_acc)
        t_lay.addWidget(self.inp_new_acc)
        t_lay.addWidget(btn_inherit)
        layout.addWidget(top_box)

        splitter = QSplitter(Qt.Horizontal)
        lease_box = QGroupBox("当前活跃 Account 粘性租约绑定表")
        l_lay = QVBoxLayout(lease_box)
        self.tbl_leases = QTableWidget(0, 6)
        self.tbl_leases.setHorizontalHeaderLabels(["业务账号 (Account)", "绑定出口 IP", "绑定节点标签", "节点 Hash", "租约到期时间", "最后访问时间"])
        self.tbl_leases.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_leases.setSelectionBehavior(QTableWidget.SelectRows)
        l_lay.addWidget(self.tbl_leases)
        splitter.addWidget(lease_box)

        ip_box = QGroupBox("平台出口 IP 租约负载分布统计")
        i_lay = QVBoxLayout(ip_box)
        self.tbl_ip_load = QTableWidget(0, 2)
        self.tbl_ip_load.setHorizontalHeaderLabels(["出口 IP 地址 (Egress IP)", "当前绑定活跃租约数 (Lease Count)"])
        self.tbl_ip_load.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        i_lay.addWidget(self.tbl_ip_load)
        splitter.addWidget(ip_box)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        return w

    # =========================================================================
    # Tab 6: 多接入点管理与代理测试工坊 (Endpoints & Proxy Tester)
    # =========================================================================
    def _build_endpoints_tester_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left_box = QGroupBox("多端口监听接入点管理 (热添加端口并独立控制管理后台 / HTTP 正向 / 反代 / SOCKS5)")
        left_lay = QVBoxLayout(left_box)

        add_row = QHBoxLayout()
        self.spn_ep_port = QSpinBox()
        self.spn_ep_port.setRange(1, 65535)
        self.spn_ep_port.setValue(2300)
        self.chk_ep_mgmt = QCheckBox("开放管理后台")
        self.chk_ep_fwd = QCheckBox("HTTP 正向")
        self.chk_ep_fwd.setChecked(True)
        self.chk_ep_rev = QCheckBox("HTTP 反代")
        self.chk_ep_rev.setChecked(True)
        self.chk_ep_socks = QCheckBox("SOCKS5")
        self.chk_ep_socks.setChecked(True)
        self.chk_ep_auth = QCheckBox("强制携带认证信息")
        btn_add_ep = QPushButton("➕ 热添加监听端口")
        btn_add_ep.setProperty("btnRole", "success")
        btn_add_ep.clicked.connect(self._create_endpoint)
        btn_del_ep = QPushButton("🗑 删除选中端口")
        btn_del_ep.setProperty("btnRole", "danger")
        btn_del_ep.clicked.connect(self._delete_selected_endpoint)

        add_row.addWidget(QLabel("端口:"))
        add_row.addWidget(self.spn_ep_port)
        add_row.addWidget(self.chk_ep_mgmt)
        add_row.addWidget(self.chk_ep_fwd)
        add_row.addWidget(self.chk_ep_rev)
        add_row.addWidget(self.chk_ep_socks)
        add_row.addWidget(self.chk_ep_auth)
        add_row.addWidget(btn_add_ep)
        add_row.addWidget(btn_del_ep)
        left_lay.addLayout(add_row)

        self.tbl_endpoints = QTableWidget(0, 8)
        self.tbl_endpoints.setHorizontalHeaderLabels(
            ["ID", "监听端口", "运行状态", "管理页面", "HTTP 正向", "HTTP 反代", "SOCKS5", "来源 / 错误"]
        )
        self.tbl_endpoints.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_endpoints.setSelectionBehavior(QTableWidget.SelectRows)
        left_lay.addWidget(self.tbl_endpoints)
        layout.addWidget(left_box, 3)

        right_box = QGroupBox("代理连通性与粘性会话实时测试工坊")
        form = QFormLayout(right_box)

        self.cmb_test_mode = QComboBox()
        self.cmb_test_mode.addItems(
            [
                "http_forward (HTTP 正向粘性代理 Platform.Account:Token)",
                "reverse_header (HTTP 反向代理 + X-Resin-Account 请求头)",
                "reverse_url (HTTP 反向代理 URL 内嵌 Platform.Account)",
            ]
        )
        self.inp_test_platform = QLineEdit("Default")
        self.inp_test_account = QLineEdit("user_tom")
        self.inp_test_url = QLineEdit("https://api.ipify.org?format=json")

        btn_run_test = QPushButton("🚀 立即发起代理请求并验证出口 IP")
        btn_run_test.setProperty("btnRole", "success")
        btn_run_test.clicked.connect(self._run_proxy_workshop_test)

        self.txt_test_output = QPlainTextEdit()
        self.txt_test_output.setReadOnly(True)
        self.txt_test_output.setPlaceholderText("点击上方测试按钮，将在此展示真实代理响应耗时、出口 IP 以及自动生成的 cURL / Python 调用代码...")

        form.addRow("接入方式:", self.cmb_test_mode)
        form.addRow("目标平台 (Platform):", self.inp_test_platform)
        form.addRow("粘性账号 (Account):", self.inp_test_account)
        form.addRow("测试目标 URL:", self.inp_test_url)
        form.addRow(btn_run_test)
        form.addRow(self.txt_test_output)

        layout.addWidget(right_box, 2)
        return w

    # =========================================================================
    # Tab 7: 请求头账号提取规则 (Account Header Rules)
    # =========================================================================
    def _build_rules_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left_box = QGroupBox("基于 URL 前缀的请求头账号提取规则列表 (零侵入识别业务 Header 绑定粘性会话)")
        left_lay = QVBoxLayout(left_box)
        self.tbl_rules = QTableWidget(0, 3)
        self.tbl_rules.setHorizontalHeaderLabels(["URL 前缀 (URL Prefix)", "按优先级提取的请求头列表 (Headers)", "最后更新时间"])
        self.tbl_rules.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_rules.setSelectionBehavior(QTableWidget.SelectRows)
        left_lay.addWidget(self.tbl_rules)

        btn_del_rule = QPushButton("🗑 删除选中 URL 前缀规则 (兜底规则 * 不可删除)")
        btn_del_rule.setProperty("btnRole", "danger")
        btn_del_rule.clicked.connect(self._delete_selected_rule)
        left_lay.addWidget(btn_del_rule)
        layout.addWidget(left_box, 3)

        right_box = QGroupBox("新增/更新提取规则 & URL 匹配仿真测试")
        form = QFormLayout(right_box)

        self.inp_rule_prefix = QLineEdit("api.openai.com/v1")
        self.inp_rule_headers = QLineEdit("Authorization, x-api-key")
        btn_save_rule = QPushButton("💾 保存 / 更新 URL 前缀提取规则")
        btn_save_rule.setProperty("btnRole", "success")
        btn_save_rule.clicked.connect(self._upsert_rule)

        self.inp_resolve_url = QLineEdit("https://api.openai.com/v1/chat/completions")
        btn_resolve = QPushButton("🔍 测试 URL 命中哪条提取规则")
        btn_resolve.clicked.connect(self._resolve_rule_test)
        self.txt_resolve_out = QPlainTextEdit()
        self.txt_resolve_out.setReadOnly(True)
        self.txt_resolve_out.setFixedHeight(140)

        form.addRow("URL 前缀*:", self.inp_rule_prefix)
        form.addRow("提取 Header (逗号分隔)*:", self.inp_rule_headers)
        form.addRow(btn_save_rule)
        form.addRow(QLabel("--- 规则匹配仿真器 ---"))
        form.addRow("待测目标 URL:", self.inp_resolve_url)
        form.addRow(btn_resolve)
        form.addRow("匹配结果:", self.txt_resolve_out)

        layout.addWidget(right_box, 2)
        return w

    # =========================================================================
    # Tab 8: 结构化请求日志与报文审计 (Request Logs)
    # =========================================================================
    def _build_request_logs_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        filter_box = QGroupBox("结构化请求日志检索与 HTTP 报文载荷审计")
        f_lay = QHBoxLayout(filter_box)

        self.inp_log_plat = QLineEdit()
        self.inp_log_plat.setPlaceholderText("平台名称...")
        self.inp_log_acc = QLineEdit()
        self.inp_log_acc.setPlaceholderText("业务账号 Account...")
        self.inp_log_host = QLineEdit()
        self.inp_log_host.setPlaceholderText("目标域名 (Target Host)...")
        self.inp_log_ip = QLineEdit()
        self.inp_log_ip.setPlaceholderText("出口 IP...")
        btn_query_logs = QPushButton("🔍 查询请求日志")
        btn_query_logs.clicked.connect(self.load_request_logs)

        f_lay.addWidget(self.inp_log_plat)
        f_lay.addWidget(self.inp_log_acc)
        f_lay.addWidget(self.inp_log_host)
        f_lay.addWidget(self.inp_log_ip)
        f_lay.addWidget(btn_query_logs)
        layout.addWidget(filter_box)

        splitter = QSplitter(Qt.Vertical)
        self.tbl_logs = QTableWidget(0, 9)
        self.tbl_logs.setHorizontalHeaderLabels(
            ["日志 ID", "时间", "代理类型", "平台 / 账号", "目标域名 / URL", "状态", "出口 IP / 节点", "耗时 (ms)", "错误详情"]
        )
        self.tbl_logs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_logs.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_logs.itemSelectionChanged.connect(self._on_log_row_selected)
        splitter.addWidget(self.tbl_logs)

        self.txt_log_payload = QPlainTextEdit()
        self.txt_log_payload.setReadOnly(True)
        self.txt_log_payload.setPlaceholderText("点击上方任意请求日志行，此处将展示该请求的基本元数据与解码后的请求头/请求体/响应头/响应体...")
        splitter.addWidget(self.txt_log_payload)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        return w

    # =========================================================================
    # Tab 9: GeoIP 与系统全局设置 (GeoIP & System Config)
    # =========================================================================
    def _build_geoip_sysconfig_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left_box = QGroupBox("运行时全局热更新配置 (PATCH /api/v1/system/config 无需重启即刻生效)")
        form = QFormLayout(left_box)

        self.chk_cfg_reqlog = QCheckBox("启用结构化请求日志 (request_log_enabled)")
        self.chk_cfg_reqlog.setChecked(True)
        self.chk_cfg_revdetail = QCheckBox("记录反向代理完整请求/响应头与正文载荷 (reverse_proxy_log_detail_enabled)")
        self.spn_cfg_max_fail = QSpinBox()
        self.spn_cfg_max_fail.setRange(1, 100)
        self.spn_cfg_max_fail.setValue(3)
        self.inp_cfg_lat_url = QLineEdit("https://www.gstatic.com/generate_204")
        self.inp_cfg_auth_domains = QLineEdit("gstatic.com, google.com, cloudflare.com, github.com")
        self.inp_cfg_lat_interval = QLineEdit("1h")
        self.inp_cfg_egress_interval = QLineEdit("24h")
        self.inp_cfg_p2c_window = QLineEdit("10m")

        btn_save_rt_cfg = QPushButton("💾 热更新保存运行时配置")
        btn_save_rt_cfg.setProperty("btnRole", "success")
        btn_save_rt_cfg.clicked.connect(self._save_runtime_config)

        form.addRow("", self.chk_cfg_reqlog)
        form.addRow("", self.chk_cfg_revdetail)
        form.addRow("最大连续失败熔断阈值:", self.spn_cfg_max_fail)
        form.addRow("延迟探测 URL:", self.inp_cfg_lat_url)
        form.addRow("延迟权重权威域名:", self.inp_cfg_auth_domains)
        form.addRow("最大延迟探测间隔:", self.inp_cfg_lat_interval)
        form.addRow("最大出口 IP 探测间隔:", self.inp_cfg_egress_interval)
        form.addRow("P2C 延迟评估窗口:", self.inp_cfg_p2c_window)
        form.addRow(btn_save_rt_cfg)

        form.addRow(QLabel("--- GeoIP 地理位置数据库查询与更新 ---"))
        self.lbl_geoip_status = QLabel("GeoIP 状态: 等待查询...")
        form.addRow(self.lbl_geoip_status)

        geo_row = QHBoxLayout()
        self.inp_geoip_ip = QLineEdit("1.1.1.1")
        btn_geo_lookup = QPushButton("查询 IP 归属地")
        btn_geo_lookup.clicked.connect(self._lookup_geoip_ip)
        btn_geo_update = QPushButton("🔄 立即更新 GeoIP 数据库")
        btn_geo_update.setProperty("btnRole", "secondary")
        btn_geo_update.clicked.connect(self._update_geoip_db)
        geo_row.addWidget(self.inp_geoip_ip)
        geo_row.addWidget(btn_geo_lookup)
        geo_row.addWidget(btn_geo_update)
        form.addRow(geo_row)

        layout.addWidget(left_box, 1)

        right_box = QGroupBox("本地引擎启动环境变量 (.env) 可视化配置")
        r_lay = QVBoxLayout(right_box)
        self.txt_env_editor = QPlainTextEdit()
        env_lines = [f"{k}={v}" for k, v in self.core_mgr.read_env().items()]
        self.txt_env_editor.setPlainText("\n".join(env_lines))
        r_lay.addWidget(self.txt_env_editor)

        env_btn_row = QHBoxLayout()
        btn_save_env = QPushButton("💾 保存 .env 并重启本地 Resin 引擎")
        btn_save_env.setProperty("btnRole", "success")
        btn_save_env.clicked.connect(self._save_env_and_restart)
        env_btn_row.addWidget(btn_save_env)
        r_lay.addLayout(env_btn_row)
        layout.addWidget(right_box, 1)

        return w

    # =========================================================================
    # Tab 10: 数据源 API 中心 (Data Source API Center)
    # =========================================================================
    def _build_datasources_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("管理 Resin 使用的所有外部数据源、DoH 安全 DNS 上游、出口探测接口与 GeoIP 源："))
        btn_test_all_ds = QPushButton("⚡ 一键测试全部数据源连通性")
        btn_test_all_ds.setProperty("btnRole", "success")
        btn_test_all_ds.clicked.connect(self._test_all_datasources)
        top_row.addWidget(btn_test_all_ds)
        layout.addLayout(top_row)

        self.tbl_datasources = QTableWidget(0, 6)
        self.tbl_datasources.setHorizontalHeaderLabels(
            ["数据源 ID", "名称", "类别", "端点 URL", "环境变量 / 源码映射", "连通性状态"]
        )
        self.tbl_datasources.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_datasources.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_datasources.itemSelectionChanged.connect(self._on_datasource_selected)
        layout.addWidget(self.tbl_datasources, 1)

        edit_box = QGroupBox("编辑选中数据源端点与持久化 (.env)")
        e_lay = QHBoxLayout(edit_box)
        self.inp_ds_id = QLineEdit()
        self.inp_ds_id.setReadOnly(True)
        self.inp_ds_id.setFixedWidth(180)
        self.inp_ds_url = QLineEdit()
        self.inp_ds_key = QLineEdit()
        self.inp_ds_key.setPlaceholderText("可选 Token / API Key")
        self.inp_ds_key.setFixedWidth(180)
        btn_save_ds = QPushButton("💾 保存至 .env")
        btn_save_ds.clicked.connect(self._save_selected_datasource)
        btn_test_ds = QPushButton("🔍 测试选中数据源")
        btn_test_ds.setProperty("btnRole", "secondary")
        btn_test_ds.clicked.connect(self._test_selected_datasource)

        e_lay.addWidget(QLabel("ID:"))
        e_lay.addWidget(self.inp_ds_id)
        e_lay.addWidget(QLabel("URL:"))
        e_lay.addWidget(self.inp_ds_url, 1)
        e_lay.addWidget(QLabel("密钥:"))
        e_lay.addWidget(self.inp_ds_key)
        e_lay.addWidget(btn_save_ds)
        e_lay.addWidget(btn_test_ds)
        layout.addWidget(edit_box)

        self._populate_datasources_table()
        return w

    # =========================================================================
    # Tab 11: 大模型与本地 API 配置 + AI 自动巡检自愈 + 自动更新
    # =========================================================================
    def _build_llm_updater_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left_col = QVBoxLayout()
        llm_box = QGroupBox(f"大模型与本地 API 配置 (内置 OpenAI 兼容网关: http://127.0.0.1:{self.local_api_port})")
        form = QFormLayout(llm_box)

        self.cmb_llm_provider = QComboBox()
        for p in self.llm_mgr.list_providers():
            tag = "[本地免Key]" if p["category"] == "local" else "[云端API]"
            self.cmb_llm_provider.addItem(f"{tag} {p['name']}", p["provider_id"])
        self.cmb_llm_provider.currentIndexChanged.connect(self._on_llm_provider_changed)

        self.inp_llm_base_url = QLineEdit()
        self.inp_llm_model = QLineEdit()
        self.inp_llm_key = QLineEdit()
        self.inp_llm_key.setEchoMode(QLineEdit.Password)
        self.inp_llm_key.setPlaceholderText("本地 Ollama / LM Studio / vLLM 无需填写 API Key")

        btn_llm_row = QHBoxLayout()
        btn_save_llm = QPushButton("💾 保存并设为当前激活模型")
        btn_save_llm.setProperty("btnRole", "success")
        btn_save_llm.clicked.connect(self._save_llm_config)
        btn_probe_llm = QPushButton("🔍 探测可用模型列表")
        btn_probe_llm.setProperty("btnRole", "secondary")
        btn_probe_llm.clicked.connect(self._probe_llm_provider)
        btn_llm_row.addWidget(btn_save_llm)
        btn_llm_row.addWidget(btn_probe_llm)

        form.addRow("选择模型服务商:", self.cmb_llm_provider)
        form.addRow("API Base URL:", self.inp_llm_base_url)
        form.addRow("模型名称 (Model):", self.inp_llm_model)
        form.addRow("API Key (可选):", self.inp_llm_key)
        form.addRow(btn_llm_row)
        left_col.addWidget(llm_box)

        upd_box = QGroupBox("版本信息与 GitHub Releases 自动更新")
        u_lay = QVBoxLayout(upd_box)
        self.lbl_update_status = QLabel(
            f"当前版本: v{__version__}\n"
            "发行仓库: https://github.com/gouqizi2214730-source/Resin/releases\n"
            "上游仓库: https://github.com/Resinat/Resin"
        )
        u_lay.addWidget(self.lbl_update_status)

        u_btn_row = QHBoxLayout()
        btn_check_upd = QPushButton("🔄 检查最新 Release 更新")
        btn_check_upd.clicked.connect(self._check_updates)
        self.btn_install_upd = QPushButton("⬇ 一键下载并安装最新 Setup.exe")
        self.btn_install_upd.setProperty("btnRole", "success")
        self.btn_install_upd.clicked.connect(self._install_latest_update)
        u_btn_row.addWidget(btn_check_upd)
        u_btn_row.addWidget(self.btn_install_upd)
        u_lay.addLayout(u_btn_row)
        left_col.addWidget(upd_box)

        layout.addLayout(left_col, 2)

        ai_box = QGroupBox("🤖 Resin AI 智能代理规则、自动自愈巡检与接入代码助手")
        ai_lay = QVBoxLayout(ai_box)

        preset_row = QHBoxLayout()
        btn_p1 = QPushButton("✨ 生成香港/日本专线过滤正则")
        btn_p1.setProperty("btnRole", "secondary")
        btn_p1.clicked.connect(
            lambda: self._run_ai_prompt("请帮我编写一个 Resin Platform 的地区与节点标签正则过滤规则，筛选香港、日本、新加坡的高速专线节点，并排除过期或流量提示节点。")
        )
        btn_p2 = QPushButton("🐍 生成 Python 粘性代理接入代码")
        btn_p2.setProperty("btnRole", "secondary")
        btn_p2.clicked.connect(
            lambda: self._run_ai_prompt("请生成 Python requests 和 httpx 接入 Resin 粘性代理（包含正向代理和反向代理 X-Resin-Account 请求头两种方式）的完整示例代码。")
        )
        btn_p3 = QPushButton("🩺 执行 AI 自愈巡检并生成诊断报告")
        btn_p3.setProperty("btnRole", "success")
        btn_p3.clicked.connect(self._diagnose_pool_with_ai)
        preset_row.addWidget(btn_p1)
        preset_row.addWidget(btn_p2)
        preset_row.addWidget(btn_p3)
        ai_lay.addLayout(preset_row)

        self.txt_ai_chat = QPlainTextEdit()
        self.txt_ai_chat.setReadOnly(True)
        self.txt_ai_chat.setPlaceholderText("在此查看 AI 助手为您生成的 Platform 正则表达式、节点池自愈巡检报告与多语言粘性代理接入代码...")
        ai_lay.addWidget(self.txt_ai_chat, 1)

        ask_row = QHBoxLayout()
        self.inp_ai_prompt = QLineEdit()
        self.inp_ai_prompt.setPlaceholderText("输入关于 Resin 粘性路由、链式代理、请求头规则或节点排障的任何问题...")
        btn_send_ai = QPushButton("发送提问")
        btn_send_ai.clicked.connect(lambda: self._run_ai_prompt(self.inp_ai_prompt.text()))
        ask_row.addWidget(self.inp_ai_prompt, 1)
        ask_row.addWidget(btn_send_ai)
        ai_lay.addLayout(ask_row)

        layout.addWidget(ai_box, 3)
        self._on_llm_provider_changed(0)
        return w

    # =========================================================================
    # 核心交互与异步数据加载逻辑
    # =========================================================================
    def _sync_api_credentials_from_inputs(self) -> None:
        self.api.configure(
            base_url=self.inp_base_url.text(),
            admin_token=self.inp_admin_token.text(),
            proxy_token=self.inp_proxy_token.text(),
        )

    def _auto_start_core_on_launch(self) -> None:
        ok, _ = self.api.healthz()
        if ok:
            self.lbl_core_badge.setText("● 网关在线 (已连接)")
            self.lbl_core_badge.setStyleSheet("color: #10B981; font-weight: bold; margin-left: 8px;")
            self.refresh_all_views()
            return

        if self.core_mgr.find_core_binary():
            started, msg = self.core_mgr.start()
            self.status_bar.showMessage(msg)
            QTimer.singleShot(1200, self.refresh_all_views)
        else:
            self.lbl_core_badge.setText("● 远程控制模式")
            self.lbl_core_badge.setStyleSheet("color: #38BDF8; font-weight: bold; margin-left: 8px;")

    def _periodic_tick(self) -> None:
        logs = self.core_mgr.get_recent_logs()
        if logs and self.txt_core_logs.toPlainText() != logs:
            self.txt_core_logs.setPlainText(logs)
            sb = self.txt_core_logs.verticalScrollBar()
            sb.setValue(sb.maximum())

        if self.tabs.currentIndex() == 0:
            self.load_dashboard_metrics()

    def _on_start_core(self) -> None:
        ok, msg = self.core_mgr.start()
        self.status_bar.showMessage(msg)
        QTimer.singleShot(1000, self.refresh_all_views)

    def _on_stop_core(self) -> None:
        ok, msg = self.core_mgr.stop()
        self.status_bar.showMessage(msg)
        self.lbl_core_badge.setText("● 本地引擎: 已停止")
        self.lbl_core_badge.setStyleSheet("color: #EF4444; font-weight: bold; margin-left: 8px;")

    def _on_restart_core(self) -> None:
        ok, msg = self.core_mgr.restart()
        self.status_bar.showMessage(msg)
        QTimer.singleShot(1000, self.refresh_all_views)

    def _toggle_windows_proxy(self, enable: bool) -> None:
        self._sync_api_credentials_from_inputs()
        import urllib.parse

        p = urllib.parse.urlparse(self.api.base_url)
        ok, msg = self.core_mgr.set_windows_system_proxy(enable, p.hostname or "127.0.0.1", p.port or 2260)
        QMessageBox.information(self, "系统代理设置", msg)

    def _copy_http_proxy_cmd(self) -> None:
        self._sync_api_credentials_from_inputs()
        token = self.api.proxy_token
        cmd = f'curl -x {self.api.base_url} -U "Default.user_01:{token}" https://api.ipify.org'
        QApplication.clipboard().setText(cmd)
        self.status_bar.showMessage(f"已复制 HTTP 粘性代理命令: {cmd}")

    def _copy_socks_proxy_cmd(self) -> None:
        self._sync_api_credentials_from_inputs()
        import urllib.parse

        p = urllib.parse.urlparse(self.api.base_url)
        host_port = f"{p.hostname or '127.0.0.1'}:{p.port or 2260}"
        token = self.api.proxy_token
        cmd = f'curl --proxy socks5h://{host_port} -U "Default.user_01:{token}" https://api.ipify.org'
        QApplication.clipboard().setText(cmd)
        self.status_bar.showMessage(f"已复制 SOCKS5 粘性代理命令: {cmd}")

    def refresh_all_views(self) -> None:
        self._sync_api_credentials_from_inputs()
        self.load_dashboard_metrics()
        self.load_subscriptions()
        self.load_platforms()
        self.load_nodes()
        self.load_endpoints()
        self.load_rules()
        self.load_request_logs()
        self.load_geoip_and_sysconfig()

    def load_dashboard_metrics(self) -> None:
        def task() -> Dict[str, Any]:
            ok_h, _ = self.api.healthz()
            _, info = self.api.get_system_info()
            _, snap = self.api.get_snapshot_node_pool()
            _, hist = self.api.get_snapshot_latency_distribution()
            _, tp = self.api.get_realtime_throughput()
            _, conns = self.api.get_realtime_connections()
            _, leases = self.api.get_realtime_leases()
            return {
                "healthy": ok_h,
                "info": info,
                "snap": snap,
                "hist": hist,
                "tp": tp,
                "conns": conns,
                "leases": leases,
            }

        def on_done(res: Any) -> None:
            if not isinstance(res, dict):
                return
            if res.get("healthy"):
                self.lbl_core_badge.setText("● 网关在线 (运行正常)")
                self.lbl_core_badge.setStyleSheet("color: #10B981; font-weight: bold; margin-left: 8px;")
            else:
                self.lbl_core_badge.setText("● 网关未连接")
                self.lbl_core_badge.setStyleSheet("color: #F59E0B; font-weight: bold; margin-left: 8px;")

            info = res.get("info")
            if isinstance(info, dict):
                self.lbl_sys_info.setText(
                    f"Resin 核心版本: {info.get('version', 'dev')} | Commit: {info.get('git_commit', '-')} | 启动时间: {info.get('started_at', '-')}"
                )

            snap = res.get("snap")
            if isinstance(snap, dict):
                total_n = snap.get("total_nodes", 0)
                healthy_n = snap.get("healthy_nodes", 0)
                egress_n = snap.get("egress_ip_count", 0)
                self.card_total_nodes.set_value(str(total_n))
                self.card_healthy_nodes.set_value(str(healthy_n), color="#10B981")
                self.card_egress_ips.set_value(
                    str(egress_n),
                    sub=f"健康独立 IP: {snap.get('healthy_egress_ip_count', 0)}",
                )
                if getattr(self, "tray_icon", None):
                    self.tray_icon.setToolTip(
                        f"{__app_name__} v{__version__}\n健康节点: {healthy_n}/{total_n} | 独立出口 IP: {egress_n}"
                    )

            tp = res.get("tp")
            if isinstance(tp, dict) and tp.get("items"):
                items = tp["items"]
                last_tp = items[-1]
                in_kb = last_tp.get("ingress_bps", 0) / 1024.0
                out_kb = last_tp.get("egress_bps", 0) / 1024.0
                self.card_throughput.set_value(f"{out_kb:.1f} KB/s", sub=f"入站: {in_kb:.1f} KB/s")
                s_out = [x.get("egress_bps", 0) / 1024.0 for x in items[-45:]]
                s_in = [x.get("ingress_bps", 0) / 1024.0 for x in items[-45:]]
                self.chart_throughput.set_series(s_out, s_in)
            else:
                self.chart_throughput.push_sample(0.0, 0.0)

            total_conns_now = 0
            conns = res.get("conns")
            if isinstance(conns, dict) and conns.get("items"):
                last_c = conns["items"][-1]
                in_c = last_c.get("inbound_connections", 0)
                out_c = last_c.get("outbound_connections", 0)
                total_conns_now = in_c + out_c
                self.card_connections.set_value(str(total_conns_now), sub=f"入站: {in_c} | 出站: {out_c}")

            active_leases_now = 0
            leases = res.get("leases")
            if isinstance(leases, dict) and leases.get("items"):
                last_l = leases["items"][-1]
                active_leases_now = last_l.get("active_leases", 0)
                self.card_leases.set_value(str(active_leases_now), color="#A855F7")

            self.chart_conns_leases.push_sample(float(total_conns_now), float(active_leases_now))

            hist = res.get("hist")
            if isinstance(hist, dict) and isinstance(hist.get("buckets"), list):
                buckets = [b for b in hist["buckets"] if b.get("count", 0) > 0]
                total_samples = max(1, hist.get("sample_count", 1))
                bin_w = hist.get("bin_width_ms", 100)
                self.tbl_latency_hist.setRowCount(len(buckets))
                for r_idx, b in enumerate(buckets):
                    le = b.get("le_ms", 0)
                    low = max(0, le - bin_w + 1)
                    cnt = b.get("count", 0)
                    pct = cnt * 100.0 / total_samples
                    bar_str = "█" * max(1, int(pct / 5)) + f" {pct:.1f}%"
                    self.tbl_latency_hist.setItem(r_idx, 0, QTableWidgetItem(f"{low} ~ {le} ms"))
                    self.tbl_latency_hist.setItem(r_idx, 1, QTableWidgetItem(str(cnt)))
                    self.tbl_latency_hist.setItem(r_idx, 2, QTableWidgetItem(bar_str))

        self.bridge.run_async(task, on_done)

    # ---- Subscriptions actions ----
    def load_subscriptions(self) -> None:
        kw = self.inp_sub_keyword.text().strip()
        self.bridge.run_async(lambda: self.api.list_subscriptions(keyword=kw), self._on_subscriptions_loaded)

    def _on_subscriptions_loaded(self, res: Tuple[bool, Any]) -> None:
        ok, data = res
        if not ok or not isinstance(data, dict):
            return
        items = data.get("items", [])
        self.tbl_subs.setRowCount(len(items))
        self._cached_subs = items
        for idx, s in enumerate(items):
            role = "链式落地" if s.get("chain_proxy") else ("链式跳板" if s.get("chain_relay") else "直出")
            state = "启用" if s.get("enabled") else "已禁用"
            info = s.get("last_error") or s.get("url") or "(本地节点内容)"
            self.tbl_subs.setItem(idx, 0, QTableWidgetItem(s.get("id", "")))
            self.tbl_subs.setItem(idx, 1, QTableWidgetItem(s.get("name", "")))
            self.tbl_subs.setItem(idx, 2, QTableWidgetItem(s.get("source_type", "remote")))
            self.tbl_subs.setItem(
                idx, 3, QTableWidgetItem(f"{s.get('node_count', 0)} / {s.get('healthy_node_count', 0)}")
            )
            self.tbl_subs.setItem(idx, 4, QTableWidgetItem(s.get("update_interval", "")))
            self.tbl_subs.setItem(idx, 5, QTableWidgetItem(role))
            self.tbl_subs.setItem(idx, 6, QTableWidgetItem(state))
            self.tbl_subs.setItem(idx, 7, QTableWidgetItem(info))

    def _on_subscription_row_selected(self) -> None:
        row = self.tbl_subs.currentRow()
        subs = getattr(self, "_cached_subs", [])
        if 0 <= row < len(subs):
            s = subs[row]
            self.inp_sub_id.setText(s.get("id", ""))
            self.inp_sub_name.setText(s.get("name", ""))
            self.cmb_sub_type.setCurrentIndex(1 if s.get("source_type") == "local" else 0)
            self.inp_sub_url.setText(s.get("url", ""))
            self.txt_sub_content.setPlainText(s.get("content", ""))
            self.inp_sub_interval.setText(s.get("update_interval", "30m"))
            self.inp_sub_evict_delay.setText(s.get("ephemeral_node_evict_delay", "72h"))
            self.chk_sub_enabled.setChecked(bool(s.get("enabled", True)))
            self.chk_sub_ephemeral.setChecked(bool(s.get("ephemeral", False)))
            self.chk_sub_incremental.setChecked(bool(s.get("incremental_alive_nodes", False)))
            if s.get("chain_proxy"):
                self.cmb_sub_chain.setCurrentIndex(1)
            elif s.get("chain_relay"):
                self.cmb_sub_chain.setCurrentIndex(2)
            else:
                self.cmb_sub_chain.setCurrentIndex(0)

    def _build_sub_payload_from_form(self) -> Dict[str, Any]:
        is_local = self.cmb_sub_type.currentIndex() == 1
        chain_idx = self.cmb_sub_chain.currentIndex()
        payload: Dict[str, Any] = {
            "name": self.inp_sub_name.text().strip(),
            "source_type": "local" if is_local else "remote",
            "update_interval": self.inp_sub_interval.text().strip() or "30m",
            "ephemeral_node_evict_delay": self.inp_sub_evict_delay.text().strip() or "72h",
            "enabled": self.chk_sub_enabled.isChecked(),
            "ephemeral": self.chk_sub_ephemeral.isChecked(),
            "incremental_alive_nodes": self.chk_sub_incremental.isChecked(),
            "chain_proxy": chain_idx == 1,
            "chain_relay": chain_idx == 2,
        }
        if is_local:
            payload["content"] = self.txt_sub_content.toPlainText().strip()
        else:
            payload["url"] = self.inp_sub_url.text().strip()
        return payload

    def _create_subscription(self) -> None:
        payload = self._build_sub_payload_from_form()
        ok, resp = self.api.create_subscription(payload)
        if ok:
            self.status_bar.showMessage("订阅创建成功，正在后台刷新节点...")
            if isinstance(resp, dict) and resp.get("id"):
                self.bridge.run_async(lambda: self.api.refresh_subscription(resp["id"]), lambda _: self.refresh_all_views())
            self.load_subscriptions()
        else:
            QMessageBox.warning(self, "创建订阅失败", str(resp))

    def _update_subscription(self) -> None:
        sub_id = self.inp_sub_id.text().strip()
        if not sub_id:
            QMessageBox.information(self, "提示", "请先在左侧表格点击选择要修改的订阅行")
            return
        payload = self._build_sub_payload_from_form()
        payload.pop("source_type", None)
        ok, resp = self.api.update_subscription(sub_id, payload)
        if ok:
            self.status_bar.showMessage(f"已更新订阅 {sub_id}")
            self.load_subscriptions()
        else:
            QMessageBox.warning(self, "更新订阅失败", str(resp))

    def _refresh_selected_subscription(self) -> None:
        sub_id = self.inp_sub_id.text().strip()
        if not sub_id:
            return
        self.status_bar.showMessage(f"正在刷新订阅 {sub_id}...")
        self.bridge.run_async(
            lambda: self.api.refresh_subscription(sub_id),
            lambda r: (self.status_bar.showMessage(f"订阅刷新完成: {r[1]}"), self.refresh_all_views()),
        )

    def _cleanup_selected_subscription(self) -> None:
        sub_id = self.inp_sub_id.text().strip()
        if not sub_id:
            return
        ok, resp = self.api.cleanup_subscription_circuit_open(sub_id)
        QMessageBox.information(self, "清理熔断节点结果", json.dumps(resp, ensure_ascii=False))
        self.refresh_all_views()

    def _delete_selected_subscription(self) -> None:
        sub_id = self.inp_sub_id.text().strip()
        if not sub_id:
            return
        ok, resp = self.api.delete_subscription(sub_id)
        if ok:
            self.inp_sub_id.clear()
            self.refresh_all_views()
        else:
            QMessageBox.warning(self, "删除失败", str(resp))

    # ---- Platforms actions ----
    def load_platforms(self) -> None:
        self.bridge.run_async(self.api.list_platforms, self._on_platforms_loaded)

    def _on_platforms_loaded(self, res: Tuple[bool, Any]) -> None:
        ok, data = res
        if not ok or not isinstance(data, dict):
            return
        items = data.get("items", [])
        self._cached_platforms = items
        self.tbl_platforms.setRowCount(len(items))

        prev_plat_id = self.cmb_lease_platform.currentData()
        self.cmb_lease_platform.blockSignals(True)
        self.cmb_lease_platform.clear()
        for idx, p in enumerate(items):
            pid = p.get("id", "")
            pname = p.get("name", "")
            self.cmb_lease_platform.addItem(f"{pname} ({p.get('routable_node_count', 0)} 节点)", pid)
            self.tbl_platforms.setItem(idx, 0, QTableWidgetItem(pid))
            self.tbl_platforms.setItem(idx, 1, QTableWidgetItem(pname))
            self.tbl_platforms.setItem(idx, 2, QTableWidgetItem(str(p.get("routable_node_count", 0))))
            self.tbl_platforms.setItem(idx, 3, QTableWidgetItem(p.get("sticky_ttl", "")))
            self.tbl_platforms.setItem(idx, 4, QTableWidgetItem(p.get("allocation_policy", "")))
            self.tbl_platforms.setItem(idx, 5, QTableWidgetItem(",".join(p.get("region_filters") or [])))
            self.tbl_platforms.setItem(idx, 6, QTableWidgetItem(" ; ".join(p.get("regex_filters") or [])))
        if prev_plat_id:
            i = self.cmb_lease_platform.findData(prev_plat_id)
            if i >= 0:
                self.cmb_lease_platform.setCurrentIndex(i)
        self.cmb_lease_platform.blockSignals(False)
        self.load_leases_and_ip_load()

    def _on_platform_row_selected(self) -> None:
        row = self.tbl_platforms.currentRow()
        plats = getattr(self, "_cached_platforms", [])
        if 0 <= row < len(plats):
            p = plats[row]
            self.inp_plat_id.setText(p.get("id", ""))
            self.inp_plat_name.setText(p.get("name", ""))
            self.inp_plat_ttl.setText(p.get("sticky_ttl", "168h"))
            self.cmb_plat_policy.setCurrentText(p.get("allocation_policy", "BALANCED"))
            self.cmb_plat_miss.setCurrentText(p.get("reverse_proxy_miss_action", "TREAT_AS_EMPTY"))
            self.cmb_plat_empty_acc.setCurrentText(
                p.get("reverse_proxy_empty_account_behavior", "ACCOUNT_HEADER_RULE")
            )
            self.inp_plat_fixed_hdr.setText(p.get("reverse_proxy_fixed_account_header", "Authorization"))
            self.txt_plat_regions.setPlainText("\n".join(p.get("region_filters") or []))
            self.txt_plat_regex.setPlainText("\n".join(p.get("regex_filters") or []))
            self.chk_plat_disable_cb.setChecked(bool(p.get("passive_circuit_breaker_disabled", False)))

    def _collect_platform_payload(self) -> Dict[str, Any]:
        regions = [x.strip().lower() for x in self.txt_plat_regions.toPlainText().splitlines() if x.strip()]
        regexes = [x.strip() for x in self.txt_plat_regex.toPlainText().splitlines() if x.strip()]
        return {
            "name": self.inp_plat_name.text().strip(),
            "sticky_ttl": self.inp_plat_ttl.text().strip() or "168h",
            "allocation_policy": self.cmb_plat_policy.currentText(),
            "reverse_proxy_miss_action": self.cmb_plat_miss.currentText(),
            "reverse_proxy_empty_account_behavior": self.cmb_plat_empty_acc.currentText(),
            "reverse_proxy_fixed_account_header": self.inp_plat_fixed_hdr.text().strip() or "Authorization",
            "region_filters": regions,
            "regex_filters": regexes,
            "passive_circuit_breaker_disabled": self.chk_plat_disable_cb.isChecked(),
        }

    def _create_platform(self) -> None:
        ok, resp = self.api.create_platform(self._collect_platform_payload())
        if ok:
            self.load_platforms()
        else:
            QMessageBox.warning(self, "创建平台失败", str(resp))

    def _update_platform(self) -> None:
        pid = self.inp_plat_id.text().strip()
        if not pid:
            return
        ok, resp = self.api.update_platform(pid, self._collect_platform_payload())
        if ok:
            self.load_platforms()
        else:
            QMessageBox.warning(self, "更新平台失败", str(resp))

    def _preview_platform_filter(self) -> None:
        p = self._collect_platform_payload()
        ok, resp = self.api.preview_platform_filter(p["regex_filters"], p["region_filters"])
        if ok and isinstance(resp, dict):
            items = resp.get("items", [])
            lines = [f"共匹配 {resp.get('total', len(items))} 个节点："]
            for n in items[:50]:
                lines.append(f"- [{n.get('region', '?')}] {n.get('display_tag', n.get('node_hash'))} (IP: {n.get('egress_ip', '-')})")
            self.txt_plat_preview.setPlainText("\n".join(lines))
        else:
            self.txt_plat_preview.setPlainText(f"预览失败: {resp}")

    def _rebuild_selected_platform(self) -> None:
        pid = self.inp_plat_id.text().strip()
        if pid:
            self.api.rebuild_platform_view(pid)
            self.load_platforms()

    def _reset_selected_platform(self) -> None:
        pid = self.inp_plat_id.text().strip()
        if pid:
            self.api.reset_platform(pid)
            self.load_platforms()

    def _delete_selected_platform(self) -> None:
        pid = self.inp_plat_id.text().strip()
        if pid:
            ok, resp = self.api.delete_platform(pid)
            if ok:
                self.load_platforms()
            else:
                QMessageBox.warning(self, "删除平台失败", str(resp))

    # ---- Nodes actions ----
    def load_nodes(self) -> None:
        filters: Dict[str, Any] = {}
        if self.inp_node_tag.text().strip():
            filters["tag_keyword"] = self.inp_node_tag.text().strip()
        if self.inp_node_region.text().strip():
            filters["region"] = self.inp_node_region.text().strip().lower()
        if self.inp_node_ip.text().strip():
            filters["egress_ip"] = self.inp_node_ip.text().strip()
        c_idx = self.cmb_node_circuit.currentIndex()
        if c_idx == 1:
            filters["circuit_open"] = "false"
        elif c_idx == 2:
            filters["circuit_open"] = "true"
        self.bridge.run_async(lambda: self.api.list_nodes(filters), self._on_nodes_loaded)

    def _on_nodes_loaded(self, res: Tuple[bool, Any]) -> None:
        ok, data = res
        if not ok or not isinstance(data, dict):
            return
        items = data.get("items", [])
        self._cached_nodes = items
        self.tbl_nodes.setRowCount(len(items))
        self.lbl_nodes_summary.setText(
            f"匹配节点总数: {data.get('total', len(items))} | 独立出口 IP: {data.get('unique_egress_ips', 0)} | 健康独立出口 IP: {data.get('unique_healthy_egress_ips', 0)}"
        )
        for idx, n in enumerate(items):
            lat = n.get("reference_latency_ms")
            lat_str = f"{lat:.1f} ms" if isinstance(lat, (int, float)) else "-"
            circuit = "🔴 熔断中" if n.get("circuit_open_since") else ("🟢 健康" if n.get("has_outbound") else "🟡 待初始化")
            chain_str = f"链式->{n.get('relay_node_tag') or '跳板'}" if n.get("chain_proxy") else "直连"
            if n.get("last_error"):
                chain_str += f" ({n['last_error']})"
            self.tbl_nodes.setItem(idx, 0, QTableWidgetItem(n.get("node_hash", "")))
            self.tbl_nodes.setItem(idx, 1, QTableWidgetItem(n.get("display_tag", "")))
            self.tbl_nodes.setItem(idx, 2, QTableWidgetItem(n.get("region", "")))
            self.tbl_nodes.setItem(idx, 3, QTableWidgetItem(n.get("egress_ip", "")))
            self.tbl_nodes.setItem(idx, 4, QTableWidgetItem(lat_str))
            self.tbl_nodes.setItem(idx, 5, QTableWidgetItem(str(n.get("failure_count", 0))))
            self.tbl_nodes.setItem(idx, 6, QTableWidgetItem(circuit))
            self.tbl_nodes.setItem(idx, 7, QTableWidgetItem(chain_str))

    def _get_selected_node_hash(self) -> str:
        row = self.tbl_nodes.currentRow()
        if row < 0:
            return ""
        item = self.tbl_nodes.item(row, 0)
        return item.text().strip() if item else ""

    def _probe_selected_node_egress(self) -> None:
        h = self._get_selected_node_hash()
        if not h:
            return
        self.status_bar.showMessage(f"正在探测节点 {h[:12]} 的出口 IP...")
        self.bridge.run_async(
            lambda: self.api.probe_node_egress(h),
            lambda r: (
                QMessageBox.information(self, "出口 IP 探测结果", json.dumps(r[1], ensure_ascii=False, indent=2)),
                self.load_nodes(),
            ),
        )

    def _probe_selected_node_latency(self) -> None:
        h = self._get_selected_node_hash()
        if not h:
            return
        self.status_bar.showMessage(f"正在探测节点 {h[:12]} 的延迟...")
        self.bridge.run_async(
            lambda: self.api.probe_node_latency(h),
            lambda r: (
                QMessageBox.information(self, "节点延迟探测结果", json.dumps(r[1], ensure_ascii=False, indent=2)),
                self.load_nodes(),
            ),
        )

    # ---- Leases & IP Load actions ----
    def load_leases_and_ip_load(self) -> None:
        pid = self.cmb_lease_platform.currentData()
        if not pid:
            return
        acc = self.inp_lease_account.text().strip()

        def task() -> Tuple[Any, Any]:
            _, l_data = self.api.list_leases(pid, account=acc)
            _, ip_data = self.api.get_ip_load(pid)
            return l_data, ip_data

        def on_done(res: Any) -> None:
            if not isinstance(res, tuple):
                return
            l_data, ip_data = res
            if isinstance(l_data, dict):
                items = l_data.get("items", [])
                self.tbl_leases.setRowCount(len(items))
                for i, l in enumerate(items):
                    self.tbl_leases.setItem(i, 0, QTableWidgetItem(l.get("account", "")))
                    self.tbl_leases.setItem(i, 1, QTableWidgetItem(l.get("egress_ip", "")))
                    self.tbl_leases.setItem(i, 2, QTableWidgetItem(l.get("node_tag", "")))
                    self.tbl_leases.setItem(i, 3, QTableWidgetItem(l.get("node_hash", "")))
                    self.tbl_leases.setItem(i, 4, QTableWidgetItem(l.get("expiry", "")))
                    self.tbl_leases.setItem(i, 5, QTableWidgetItem(l.get("last_accessed", "")))
            if isinstance(ip_data, dict):
                entries = ip_data.get("items", [])
                self.tbl_ip_load.setRowCount(len(entries))
                for i, e in enumerate(entries):
                    self.tbl_ip_load.setItem(i, 0, QTableWidgetItem(e.get("egress_ip", "")))
                    self.tbl_ip_load.setItem(i, 1, QTableWidgetItem(str(e.get("lease_count", 0))))

        self.bridge.run_async(task, on_done)

    def _delete_selected_lease(self) -> None:
        pid = self.cmb_lease_platform.currentData()
        row = self.tbl_leases.currentRow()
        if not pid or row < 0:
            return
        acc_item = self.tbl_leases.item(row, 0)
        if acc_item:
            self.api.delete_lease(pid, acc_item.text())
            self.load_leases_and_ip_load()

    def _clear_all_platform_leases(self) -> None:
        pid = self.cmb_lease_platform.currentData()
        if pid:
            self.api.delete_all_leases(pid)
            self.load_leases_and_ip_load()

    def _on_inherit_lease(self) -> None:
        plat_text = self.cmb_lease_platform.currentText().split(" (")[0].strip() or "Default"
        parent_acc = self.inp_parent_acc.text().strip()
        new_acc = self.inp_new_acc.text().strip()
        if not parent_acc or not new_acc:
            QMessageBox.information(self, "提示", "请输入父账号与新子账号名称")
            return
        ok, resp = self.api.inherit_lease(plat_text, parent_acc, new_acc)
        if ok:
            self.status_bar.showMessage(f"已将 {parent_acc} 的出口租约继承给 {new_acc}")
            self.load_leases_and_ip_load()
        else:
            QMessageBox.warning(self, "租约继承失败", str(resp))

    # ---- Endpoints & Proxy Tester actions ----
    def load_endpoints(self) -> None:
        self.bridge.run_async(self.api.list_endpoints, self._on_endpoints_loaded)

    def _on_endpoints_loaded(self, res: Tuple[bool, Any]) -> None:
        ok, data = res
        if not ok or not isinstance(data, dict):
            return
        items = data.get("items", [])
        self.tbl_endpoints.setRowCount(len(items))
        for i, ep in enumerate(items):
            self.tbl_endpoints.setItem(i, 0, QTableWidgetItem(ep.get("id", "")))
            self.tbl_endpoints.setItem(i, 1, QTableWidgetItem(str(ep.get("port", ""))))
            self.tbl_endpoints.setItem(i, 2, QTableWidgetItem(ep.get("status", "")))
            self.tbl_endpoints.setItem(i, 3, QTableWidgetItem("✅" if ep.get("allow_management") else "❌"))
            self.tbl_endpoints.setItem(i, 4, QTableWidgetItem("✅" if ep.get("allow_http_forward") else "❌"))
            self.tbl_endpoints.setItem(i, 5, QTableWidgetItem("✅" if ep.get("allow_http_reverse") else "❌"))
            self.tbl_endpoints.setItem(i, 6, QTableWidgetItem("✅" if ep.get("allow_socks5") else "❌"))
            self.tbl_endpoints.setItem(
                i, 7, QTableWidgetItem(ep.get("last_error") or ep.get("source", ""))
            )

    def _create_endpoint(self) -> None:
        payload = {
            "port": self.spn_ep_port.value(),
            "enabled": True,
            "allow_management": self.chk_ep_mgmt.isChecked(),
            "allow_proxy": True,
            "allow_http_forward": self.chk_ep_fwd.isChecked(),
            "allow_http_reverse": self.chk_ep_rev.isChecked(),
            "allow_socks5": self.chk_ep_socks.isChecked(),
            "require_proxy_auth_info": self.chk_ep_auth.isChecked(),
        }
        ok, resp = self.api.create_endpoint(payload)
        if ok:
            self.load_endpoints()
        else:
            QMessageBox.warning(self, "添加接入点失败", str(resp))

    def _delete_selected_endpoint(self) -> None:
        row = self.tbl_endpoints.currentRow()
        if row < 0:
            return
        ep_id = self.tbl_endpoints.item(row, 0).text()
        ok, resp = self.api.delete_endpoint(ep_id)
        if ok:
            self.load_endpoints()
        else:
            QMessageBox.warning(self, "删除端口失败", str(resp))

    def _run_proxy_workshop_test(self) -> None:
        self._sync_api_credentials_from_inputs()
        mode_raw = self.cmb_test_mode.currentText().split(" ")[0]
        plat = self.inp_test_platform.text().strip() or "Default"
        acc = self.inp_test_account.text().strip()
        url = self.inp_test_url.text().strip() or "https://api.ipify.org?format=json"

        self.txt_test_output.setPlainText("正在通过 Resin 代理池发起请求...")
        self.bridge.run_async(
            lambda: self.api.test_proxy_connection(mode_raw, plat, acc, url),
            lambda r: self.txt_test_output.setPlainText(json.dumps(r, ensure_ascii=False, indent=2)),
        )

    # ---- Rules actions ----
    def load_rules(self) -> None:
        self.bridge.run_async(self.api.list_rules, self._on_rules_loaded)

    def _on_rules_loaded(self, res: Tuple[bool, Any]) -> None:
        ok, data = res
        if not ok or not isinstance(data, dict):
            return
        items = data.get("items", [])
        self.tbl_rules.setRowCount(len(items))
        for i, r in enumerate(items):
            self.tbl_rules.setItem(i, 0, QTableWidgetItem(r.get("url_prefix", "")))
            self.tbl_rules.setItem(i, 1, QTableWidgetItem(", ".join(r.get("headers") or [])))
            self.tbl_rules.setItem(i, 2, QTableWidgetItem(r.get("updated_at", "")))

    def _upsert_rule(self) -> None:
        prefix = self.inp_rule_prefix.text().strip()
        headers = [h.strip() for h in self.inp_rule_headers.text().split(",") if h.strip()]
        ok, resp = self.api.upsert_rule(prefix, headers)
        if ok:
            self.load_rules()
        else:
            QMessageBox.warning(self, "保存规则失败", str(resp))

    def _delete_selected_rule(self) -> None:
        row = self.tbl_rules.currentRow()
        if row < 0:
            return
        prefix = self.tbl_rules.item(row, 0).text()
        ok, resp = self.api.delete_rule(prefix)
        if ok:
            self.load_rules()
        else:
            QMessageBox.warning(self, "删除规则失败", str(resp))

    def _resolve_rule_test(self) -> None:
        ok, resp = self.api.resolve_rule(self.inp_resolve_url.text().strip())
        self.txt_resolve_out.setPlainText(json.dumps(resp, ensure_ascii=False, indent=2))

    # ---- Request Logs actions ----
    def load_request_logs(self) -> None:
        filters: Dict[str, Any] = {}
        if self.inp_log_plat.text().strip():
            filters["platform_name"] = self.inp_log_plat.text().strip()
        if self.inp_log_acc.text().strip():
            filters["account"] = self.inp_log_acc.text().strip()
        if self.inp_log_host.text().strip():
            filters["target_host"] = self.inp_log_host.text().strip()
        if self.inp_log_ip.text().strip():
            filters["egress_ip"] = self.inp_log_ip.text().strip()
        self.bridge.run_async(lambda: self.api.list_request_logs(filters), self._on_request_logs_loaded)

    def _on_request_logs_loaded(self, res: Tuple[bool, Any]) -> None:
        ok, data = res
        if not ok or not isinstance(data, dict):
            return
        items = data.get("items", [])
        self._cached_logs = items
        self.tbl_logs.setRowCount(len(items))
        ptype_map = {1: "HTTP正向", 2: "SOCKS5", 3: "HTTP反代"}
        for i, l in enumerate(items):
            p_str = ptype_map.get(l.get("proxy_type", 1), "代理")
            status_str = f"HTTP {l.get('http_status', 0)}" if l.get("net_ok") else f"失败 ({l.get('resin_error') or 'ERR'})"
            self.tbl_logs.setItem(i, 0, QTableWidgetItem(l.get("id", "")))
            self.tbl_logs.setItem(i, 1, QTableWidgetItem(l.get("ts", "")))
            self.tbl_logs.setItem(i, 2, QTableWidgetItem(p_str))
            self.tbl_logs.setItem(
                i, 3, QTableWidgetItem(f"{l.get('platform_name', '')} / {l.get('account', '-')}")
            )
            self.tbl_logs.setItem(
                i, 4, QTableWidgetItem(f"{l.get('http_method', '')} {l.get('target_host', '')}")
            )
            self.tbl_logs.setItem(i, 5, QTableWidgetItem(status_str))
            self.tbl_logs.setItem(
                i, 6, QTableWidgetItem(f"{l.get('egress_ip', '-')} ({l.get('node_tag', '-')})")
            )
            self.tbl_logs.setItem(i, 7, QTableWidgetItem(str(l.get("duration_ms", 0))))
            self.tbl_logs.setItem(i, 8, QTableWidgetItem(l.get("upstream_err_msg", "")))

    def _on_log_row_selected(self) -> None:
        row = self.tbl_logs.currentRow()
        logs = getattr(self, "_cached_logs", [])
        if not (0 <= row < len(logs)):
            return
        log_item = logs[row]
        log_id = log_item.get("id", "")
        summary = json.dumps(log_item, ensure_ascii=False, indent=2)
        if not log_item.get("payload_present"):
            self.txt_log_payload.setPlainText(f"=== 请求结构化摘要 ===\n{summary}\n\n(该请求未开启详细报文抓取)")
            return

        def fetch_payload() -> Tuple[bool, Any]:
            return self.api.get_request_log_payloads(log_id)

        def on_done(res: Tuple[bool, Any]) -> None:
            ok, p = res
            if not ok or not isinstance(p, dict):
                self.txt_log_payload.setPlainText(summary)
                return
            detail = (
                f"=== 请求结构化摘要 ===\n{summary}\n\n"
                f"=== Request Headers ===\n{p.get('req_headers_text', '')}\n\n"
                f"=== Request Body ===\n{p.get('req_body_text', '')}\n\n"
                f"=== Response Headers ===\n{p.get('resp_headers_text', '')}\n\n"
                f"=== Response Body ===\n{p.get('resp_body_text', '')}"
            )
            self.txt_log_payload.setPlainText(detail)

        self.bridge.run_async(fetch_payload, on_done)

    # ---- GeoIP & System Config actions ----
    def load_geoip_and_sysconfig(self) -> None:
        def task() -> Tuple[Any, Any]:
            _, g = self.api.get_geoip_status()
            _, c = self.api.get_system_config()
            return g, c

        def on_done(res: Any) -> None:
            if not isinstance(res, tuple):
                return
            g, c = res
            if isinstance(g, dict):
                self.lbl_geoip_status.setText(
                    f"GeoIP 数据库更新时间: {g.get('db_mtime') or '尚未下载'} | 下次计划更新: {g.get('next_scheduled_update') or '-'}"
                )
            if isinstance(c, dict):
                self.chk_cfg_reqlog.setChecked(bool(c.get("request_log_enabled", True)))
                self.chk_cfg_revdetail.setChecked(bool(c.get("reverse_proxy_log_detail_enabled", False)))
                self.spn_cfg_max_fail.setValue(int(c.get("max_consecutive_failures", 3)))
                self.inp_cfg_lat_url.setText(c.get("latency_test_url", "https://www.gstatic.com/generate_204"))
                self.inp_cfg_auth_domains.setText(", ".join(c.get("latency_authorities") or []))
                self.inp_cfg_lat_interval.setText(str(c.get("max_latency_test_interval", "1h")))
                self.inp_cfg_egress_interval.setText(str(c.get("max_egress_test_interval", "24h")))
                self.inp_cfg_p2c_window.setText(str(c.get("p2c_latency_window", "10m")))

        self.bridge.run_async(task, on_done)

    def _save_runtime_config(self) -> None:
        domains = [d.strip() for d in self.inp_cfg_auth_domains.text().split(",") if d.strip()]
        patch = {
            "request_log_enabled": self.chk_cfg_reqlog.isChecked(),
            "reverse_proxy_log_detail_enabled": self.chk_cfg_revdetail.isChecked(),
            "max_consecutive_failures": self.spn_cfg_max_fail.value(),
            "latency_test_url": self.inp_cfg_lat_url.text().strip(),
            "latency_authorities": domains,
            "max_latency_test_interval": self.inp_cfg_lat_interval.text().strip(),
            "max_egress_test_interval": self.inp_cfg_egress_interval.text().strip(),
            "p2c_latency_window": self.inp_cfg_p2c_window.text().strip(),
        }
        ok, resp = self.api.patch_system_config(patch)
        if ok:
            QMessageBox.information(self, "保存成功", "运行时全局设置已热更新生效！")
        else:
            QMessageBox.warning(self, "热更新失败", str(resp))

    def _lookup_geoip_ip(self) -> None:
        ip = self.inp_geoip_ip.text().strip()
        ok, resp = self.api.lookup_geoip(ip)
        QMessageBox.information(self, "GeoIP 查询结果", json.dumps(resp, ensure_ascii=False, indent=2))

    def _update_geoip_db(self) -> None:
        self.status_bar.showMessage("正在后台更新 GeoIP 数据库...")
        self.bridge.run_async(
            self.api.update_geoip_now,
            lambda r: (
                QMessageBox.information(self, "GeoIP 更新", json.dumps(r[1], ensure_ascii=False)),
                self.load_geoip_and_sysconfig(),
            ),
        )

    def _save_env_and_restart(self) -> None:
        raw = self.txt_env_editor.toPlainText()
        env_dict: Dict[str, str] = {}
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env_dict[k.strip()] = v.strip()
        self.core_mgr.write_env(env_dict)
        port = env_dict.get("RESIN_PORT", "2260")
        self.inp_base_url.setText(f"http://127.0.0.1:{port}")
        self.inp_admin_token.setText(env_dict.get("RESIN_ADMIN_TOKEN", ""))
        self.inp_proxy_token.setText(env_dict.get("RESIN_PROXY_TOKEN", ""))
        self._on_restart_core()

    # ---- Data Sources actions ----
    def _populate_datasources_table(self) -> None:
        sources = self.ds_mgr.list_sources()
        self._cached_ds = sources
        self.tbl_datasources.setRowCount(len(sources))
        for i, s in enumerate(sources):
            self.tbl_datasources.setItem(i, 0, QTableWidgetItem(s["source_id"]))
            self.tbl_datasources.setItem(i, 1, QTableWidgetItem(s["name"]))
            self.tbl_datasources.setItem(i, 2, QTableWidgetItem(s["category"]))
            self.tbl_datasources.setItem(i, 3, QTableWidgetItem(s["endpoint_url"]))
            self.tbl_datasources.setItem(i, 4, QTableWidgetItem(f"{s['env_key']} ({s['internal_module']})"))
            self.tbl_datasources.setItem(i, 5, QTableWidgetItem("点击测试连通性"))

    def _on_datasource_selected(self) -> None:
        row = self.tbl_datasources.currentRow()
        sources = getattr(self, "_cached_ds", [])
        if 0 <= row < len(sources):
            s = sources[row]
            self.inp_ds_id.setText(s["source_id"])
            self.inp_ds_url.setText(s["endpoint_url"])
            self.inp_ds_key.setText(s.get("api_key", ""))

    def _save_selected_datasource(self) -> None:
        sid = self.inp_ds_id.text().strip()
        if not sid:
            return
        self.ds_mgr.update_source(sid, self.inp_ds_url.text(), self.inp_ds_key.text())
        self._populate_datasources_table()
        self.status_bar.showMessage(f"已保存数据源 {sid} 并同步至 .env")

    def _test_selected_datasource(self) -> None:
        sid = self.inp_ds_id.text().strip()
        row = self.tbl_datasources.currentRow()
        if not sid or row < 0:
            return
        res = self.ds_mgr.test_connectivity(sid)
        self.tbl_datasources.setItem(row, 5, QTableWidgetItem(res["message"]))

    def _test_all_datasources(self) -> None:
        sources = self.ds_mgr.list_sources()
        for idx, s in enumerate(sources):
            res = self.ds_mgr.test_connectivity(s["source_id"])
            self.tbl_datasources.setItem(idx, 5, QTableWidgetItem(res["message"]))
            QApplication.processEvents()

    # ---- LLM & Auto-Update actions ----
    def _on_llm_provider_changed(self, _: int) -> None:
        pid = self.cmb_llm_provider.currentData()
        cfg = self.llm_mgr.get_provider_config(pid)
        self.inp_llm_base_url.setText(cfg["base_url"])
        self.inp_llm_model.setText(cfg["model"])
        self.inp_llm_key.setText(cfg["api_key"])

    def _save_llm_config(self) -> None:
        pid = self.cmb_llm_provider.currentData()
        self.llm_mgr.update_provider_config(
            provider_id=pid,
            base_url=self.inp_llm_base_url.text(),
            model=self.inp_llm_model.text(),
            api_key=self.inp_llm_key.text(),
            set_active=True,
        )
        self.status_bar.showMessage(f"已保存并激活模型服务商: {pid}")

    def _probe_llm_provider(self) -> None:
        self._save_llm_config()
        pid = self.cmb_llm_provider.currentData()
        res = self.llm_mgr.probe_local_models(pid)
        QMessageBox.information(self, "模型探测结果", json.dumps(res, ensure_ascii=False, indent=2))

    def _run_ai_prompt(self, prompt: str) -> None:
        if not prompt.strip():
            return
        self._save_llm_config()
        self.txt_ai_chat.setPlainText("🤖 正在思考并生成方案...")
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Resin 智能代理池网关的资深架构师助手。Resin 支持 HTTP/SOCKS5 正向代理与 HTTP 反向代理，"
                    "采用 Platform.Account:Token 身份格式或 X-Resin-Account 请求头实现账号级粘性出口 IP 绑定。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        self.bridge.run_async(
            lambda: self.llm_mgr.chat_completion(messages),
            lambda r: self.txt_ai_chat.setPlainText(r.get("content", str(r))),
        )

    def _diagnose_pool_with_ai(self) -> None:
        patrol_res = self.watchdog.run_patrol_once()
        _, snap = self.api.get_snapshot_node_pool()
        prompt = (
            f"刚完成了 AI 自动巡检自愈，执行摘要为：{patrol_res.get('summary')}。\n"
            f"当前 Resin 节点池实时快照为：{json.dumps(snap, ensure_ascii=False)}。\n"
            "请结合自愈结果分析当前节点池健康率，并给出进一步的 Platform 策略与探测间隔调优建议。"
        )
        self._run_ai_prompt(prompt)

    def _check_updates(self) -> None:
        self.lbl_update_status.setText("正在检查 GitHub Releases 最新版本...")
        self.bridge.run_async(self.updater.check_for_updates, self._on_update_checked)

    def _on_update_checked(self, res: Dict[str, Any]) -> None:
        self._latest_update_info = res
        self.lbl_update_status.setText(
            f"{res.get('message', '')}\n"
            f"当前版本: v{res.get('current_version')} | 最新版本: v{res.get('latest_version')}\n"
            f"Windows 安装包: {res.get('setup_exe_url') or '见 Release 页面'}\n"
            f"Android APK: {res.get('apk_url') or '见 Release 页面'}"
        )

    def _install_latest_update(self) -> None:
        info = getattr(self, "_latest_update_info", None) or self.updater.check_for_updates()
        url = info.get("setup_exe_url", "")
        if not url:
            webbrowser.open(info.get("html_url", "https://github.com/gouqizi2214730-source/Resin/releases"))
            return
        res = self.updater.download_and_install_windows_setup(url)
        QMessageBox.information(self, "更新安装", res.get("message", ""))

    def closeEvent(self, event: Any) -> None:
        if not self._force_quit and getattr(self, "tray_icon", None) and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                __app_name__,
                "Resin 已最小化至系统托盘继续在后台提供代理池服务。双击托盘图标可恢复主窗口。",
                QSystemTrayIcon.Information,
                2500,
            )
            return
        self.watchdog.stop()
        if self.core_mgr.is_running():
            self.core_mgr.stop()
        super().closeEvent(event)


def launch_desktop_gui(
    core_mgr: Optional[ResinCoreProcessManager] = None,
    api_client: Optional[ResinAPIClient] = None,
    llm_mgr: Optional[LLMProviderManager] = None,
    ds_mgr: Optional[DataSourceManager] = None,
    watchdog: Optional[AutoHealWatchdog] = None,
    local_api_port: int = 8787,
    start_minimized: bool = False,
) -> int:
    enable_windows_hidpi_and_app_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(DARK_STYLESHEET)
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    win = ResinMainWindow(
        core_mgr=core_mgr,
        api_client=api_client,
        llm_mgr=llm_mgr,
        ds_mgr=ds_mgr,
        watchdog=watchdog,
        local_api_port=local_api_port,
    )
    if start_minimized and getattr(win, "tray_icon", None):
        win.hide()
    else:
        win.show()
    return app.exec()
