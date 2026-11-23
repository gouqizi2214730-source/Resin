package com.resinat.resin.android

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.Locale

class MainActivity : AppCompatActivity() {

    companion object {
        private const val REQ_CODE_VPN = 2261
    }

    private val uiHandler = Handler(Looper.getMainLooper())
    private lateinit var rootLayout: LinearLayout
    private lateinit var headerLayout: LinearLayout
    private lateinit var udcOpticalBar: LinearLayout
    private lateinit var udcSensorPill: TextView
    private lateinit var contentContainer: LinearLayout
    private lateinit var adaptiveManager: AdaptiveScreenManager
    private var activeTabIndex = 0

    // Connection & Screen settings
    private var gatewayUrl = "http://127.0.0.1:2260"
    private var adminToken = "admin123"
    private var proxyToken = "my-token"
    private var bootAutoStart = true
    private var vpnAppMode = 0
    private var vpnAppPackages = "com.android.chrome"
    private var screenAdaptMode = AdaptiveScreenManager.MODE_AUTO
    private var screenExtraTopDp = 0
    private var screenCurvedEdgeDp = 0

    // LLM Settings
    private var llmBaseUrl = "https://api.deepseek.com/v1"
    private var llmModel = "deepseek-chat"
    private var llmApiKey = ""

    // Dashboard live views
    private var tvEngineStatus: TextView? = null
    private var tvVpnStatus: TextView? = null
    private var tvScreenDiag: TextView? = null
    private var tvMetricsSummary: TextView? = null
    private var tvCoreLogs: TextView? = null
    private var webViewInstance: WebView? = null

    private val logRefreshRunnable = object : Runnable {
        override fun run() {
            if (activeTabIndex == 0) {
                tvCoreLogs?.text = ResinCoreService.getLogsText()
                val running = ResinCoreService.isRunning()
                tvEngineStatus?.text = if (running) {
                    "● 本地内置 Resin 引擎: 运行中 ($gatewayUrl)"
                } else {
                    "● 本地内置 Resin 引擎: 未启动 (可点击下方启动或连接远程网关)"
                }
                tvEngineStatus?.setTextColor(
                    if (running) Color.parseColor("#10B981") else Color.parseColor("#F59E0B")
                )

                val vpnOn = ResinVpnService.isVpnActive()
                tvVpnStatus?.text = if (vpnOn) {
                    "🟢 VPN 透明代理隧道: 已开启 (流量已导向 Resin 网关)"
                } else {
                    "⚪ VPN 透明代理隧道: 未开启"
                }
                tvVpnStatus?.setTextColor(
                    if (vpnOn) Color.parseColor("#10B981") else Color.parseColor("#94A3B8")
                )
            }
            uiHandler.postDelayed(this, 2500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        loadPrefs()

        adaptiveManager = AdaptiveScreenManager(this)
        adaptiveManager.configureWindowEdgeToEdge()

        rootLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0F172A"))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        // Top App Header (支持异形屏挖孔/刘海四向避让 + 屏下摄像头 UDC 光学防眩光带)
        headerLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#1E293B"))
            setPadding(dp(16), dp(28), dp(16), dp(10))
        }

        // 屏下摄像头 (UDC) 低亮度纯黑光学消光保护区
        udcOpticalBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            visibility = View.GONE
            setPadding(0, 0, 0, dp(6))
        }
        udcSensorPill = TextView(this).apply {
            text = "◉ UDC 屏下镜头光学消光保护区"
            setTextColor(Color.parseColor("#334155"))
            textSize = 10f
            gravity = Gravity.CENTER
            background = roundedBg("#03050A", dp(12), "#1E293B")
            setPadding(dp(14), dp(3), dp(14), dp(3))
        }
        udcOpticalBar.addView(udcSensorPill)
        headerLayout.addView(udcOpticalBar)

        val titleRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val tvTitle = TextView(this).apply {
            text = "🛡️ Resin 智能代理池网关 v1.3.1"
            setTextColor(Color.parseColor("#38BDF8"))
            textSize = 17f
            setTypeface(typeface, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val btnQuickHeal = createButton("🩺 AI 自愈", "#0284C7") {
            runAiAutoHealPatrol()
        }.apply {
            val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            lp.rightMargin = dp(6)
            layoutParams = lp
        }
        val btnQuickStart = createButton("▶ 启动引擎", "#059669") {
            startLocalEngine()
        }
        titleRow.addView(tvTitle)
        titleRow.addView(btnQuickHeal)
        titleRow.addView(btnQuickStart)
        headerLayout.addView(titleRow)

        // Navigation Tabs Bar
        val navScroll = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            setPadding(0, dp(8), 0, 0)
        }
        val navRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
        }
        val tabs = listOf(
            "🚀 总览与屏幕自适应",
            "📡 订阅与节点",
            "🎯 平台与租约",
            "🔌 接入点与日志",
            "🤖 AI自愈与数据源",
            "🌐 Web控制台"
        )
        val tabButtons = mutableListOf<Button>()
        tabs.forEachIndexed { idx, label ->
            val btn = createButton(label, if (idx == 0) "#0284C7" else "#334155") {
                activeTabIndex = idx
                tabButtons.forEachIndexed { bIdx, b ->
                    b.background = roundedBg(if (bIdx == idx) "#0284C7" else "#334155", dp(6))
                }
                switchTab(idx)
            }.apply {
                val lp = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                )
                lp.setMargins(0, 0, dp(8), 0)
                layoutParams = lp
            }
            tabButtons.add(btn)
            navRow.addView(btn)
        }
        navScroll.addView(navRow)
        headerLayout.addView(navScroll)
        rootLayout.addView(headerLayout)

        contentContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
        }
        rootLayout.addView(contentContainer)
        setContentView(rootLayout)

        // 绑定异形屏、挖孔屏、屏下摄像头 (UDC)、折叠屏与软键盘自适应 Insets 监听器
        adaptiveManager.attachAdaptiveInsetsListener(rootLayout) { profile ->
            applyScreenAdaptation(profile)
        }

        switchTab(0)
        uiHandler.post(logRefreshRunnable)
        startLocalEngine()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        adaptiveManager.recomputeNow(rootLayout) { profile ->
            applyScreenAdaptation(profile)
        }
    }

    private fun applyScreenAdaptation(profile: AdaptiveScreenManager.ScreenAdaptationProfile) {
        val horizPadBase = if (profile.isFoldableOrTablet) dp(24) else dp(14)
        headerLayout.setPadding(
            horizPadBase + profile.safeLeftPx + profile.headerLeftShiftPx,
            profile.safeTopPx,
            horizPadBase + profile.safeRightPx + profile.headerRightShiftPx,
            dp(10)
        )

        if (profile.showUdcOpticalGuard) {
            udcOpticalBar.visibility = View.VISIBLE
            udcSensorPill.minWidth = profile.udcZoneWidthPx
        } else {
            udcOpticalBar.visibility = View.GONE
        }

        contentContainer.setPadding(
            profile.safeLeftPx,
            0,
            profile.safeRightPx,
            profile.safeBottomPx
        )

        tvScreenDiag?.text = adaptiveManager.formatDiagnosticsText()
    }

    private fun loadPrefs() {
        val prefs = getSharedPreferences("resin_prefs", Context.MODE_PRIVATE)
        gatewayUrl = prefs.getString("gateway_url", "http://127.0.0.1:2260") ?: "http://127.0.0.1:2260"
        adminToken = prefs.getString("admin_token", "admin123") ?: "admin123"
        proxyToken = prefs.getString("proxy_token", "my-token") ?: "my-token"
        bootAutoStart = prefs.getBoolean("boot_auto_start", true)
        vpnAppMode = prefs.getInt("vpn_app_mode", 0)
        vpnAppPackages = prefs.getString("vpn_app_packages", "com.android.chrome") ?: "com.android.chrome"
        screenAdaptMode = prefs.getInt("screen_adapt_mode", AdaptiveScreenManager.MODE_AUTO)
        screenExtraTopDp = prefs.getInt("screen_extra_top_dp", 0)
        screenCurvedEdgeDp = prefs.getInt("screen_curved_edge_dp", 0)
        llmBaseUrl = prefs.getString("llm_base_url", "https://api.deepseek.com/v1") ?: "https://api.deepseek.com/v1"
        llmModel = prefs.getString("llm_model", "deepseek-chat") ?: "deepseek-chat"
        llmApiKey = prefs.getString("llm_api_key", "") ?: ""
    }

    private fun savePrefs(port: String = "2260") {
        val prefs = getSharedPreferences("resin_prefs", Context.MODE_PRIVATE)
        prefs.edit()
            .putString("gateway_url", gatewayUrl)
            .putString("port", port)
            .putString("admin_token", adminToken)
            .putString("proxy_token", proxyToken)
            .putBoolean("boot_auto_start", bootAutoStart)
            .putInt("vpn_app_mode", vpnAppMode)
            .putString("vpn_app_packages", vpnAppPackages)
            .putInt("screen_adapt_mode", screenAdaptMode)
            .putInt("screen_extra_top_dp", screenExtraTopDp)
            .putInt("screen_curved_edge_dp", screenCurvedEdgeDp)
            .putString("llm_base_url", llmBaseUrl)
            .putString("llm_model", llmModel)
            .putString("llm_api_key", llmApiKey)
            .apply()
    }

    private fun startLocalEngine() {
        val uri = Uri.parse(gatewayUrl)
        val port = if (uri.port > 0) uri.port.toString() else "2260"
        savePrefs(port)
        val svcIntent = Intent(this, ResinCoreService::class.java).apply {
            action = ResinCoreService.ACTION_START
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(svcIntent)
        } else {
            startService(svcIntent)
        }
        uiHandler.postDelayed({ refreshDashboardMetrics() }, 1200)
    }

    private fun stopLocalEngine() {
        val svcIntent = Intent(this, ResinCoreService::class.java).apply {
            action = ResinCoreService.ACTION_STOP
        }
        startService(svcIntent)
        Toast.makeText(this, "已发送停止本地引擎指令", Toast.LENGTH_SHORT).show()
    }

    private fun startVpnTakeover() {
        val uri = Uri.parse(gatewayUrl)
        val port = if (uri.port > 0) uri.port.toString() else "2260"
        savePrefs(port)
        val prepIntent = VpnService.prepare(this)
        if (prepIntent != null) {
            @Suppress("DEPRECATION")
            startActivityForResult(prepIntent, REQ_CODE_VPN)
        } else {
            onActivityResult(REQ_CODE_VPN, Activity.RESULT_OK, null)
        }
    }

    private fun stopVpnTakeover() {
        val svcIntent = Intent(this, ResinVpnService::class.java).apply {
            action = ResinVpnService.ACTION_VPN_STOP
        }
        startService(svcIntent)
        Toast.makeText(this, "已关闭 VPN 透明代理接管", Toast.LENGTH_SHORT).show()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_CODE_VPN && resultCode == Activity.RESULT_OK) {
            val svcIntent = Intent(this, ResinVpnService::class.java).apply {
                action = ResinVpnService.ACTION_VPN_START
            }
            startService(svcIntent)
            Toast.makeText(this, "已开启 Android VPN 透明代理接管", Toast.LENGTH_SHORT).show()
        }
    }

    private fun runAiAutoHealPatrol() {
        Toast.makeText(this, "🩺 正在执行 AI 节点池巡检与熔断节点自愈...", Toast.LENGTH_SHORT).show()
        Thread {
            val actions = mutableListOf<String>()
            val (okS, subsRaw) = apiRequest("GET", "/api/v1/subscriptions?limit=100&offset=0")
            if (okS) {
                try {
                    val items = JSONObject(subsRaw).optJSONArray("items") ?: JSONArray()
                    for (i in 0 until items.length()) {
                        val s = items.getJSONObject(i)
                        if (!s.optBoolean("enabled", true)) continue
                        val sid = s.optString("id")
                        val sname = s.optString("name", sid)
                        val total = s.optInt("node_count", 0)
                        val healthy = s.optInt("healthy_node_count", 0)
                        if (total > 0 && healthy < total) {
                            val (okC, cRaw) = apiRequest("POST", "/api/v1/subscriptions/$sid/actions/cleanup-circuit-open-nodes", "{}")
                            if (okC) {
                                val cleaned = JSONObject(cRaw).optInt("cleaned_count", 0)
                                if (cleaned > 0) actions.add("清理[$sname]熔断节点 ${cleaned}个")
                            }
                        }
                        if (total == 0 || (total > 0 && healthy.toDouble() / total < 0.4)) {
                            apiRequest("POST", "/api/v1/subscriptions/$sid/actions/refresh", "{}")
                            actions.add("刷新低健康率订阅[$sname]")
                        }
                    }
                } catch (_: Exception) {}
            }

            val (okN, nodesRaw) = apiRequest("GET", "/api/v1/nodes?limit=10&offset=0&circuit_open=true")
            if (okN) {
                try {
                    val items = JSONObject(nodesRaw).optJSONArray("items") ?: JSONArray()
                    var probed = 0
                    for (i in 0 until minOf(4, items.length())) {
                        val nh = items.getJSONObject(i).optString("node_hash")
                        if (nh.isNotEmpty()) {
                            apiRequest("POST", "/api/v1/nodes/$nh/actions/probe-latency", "{}")
                            probed++
                        }
                    }
                    if (probed > 0) actions.add("主动探测恢复 $probed 个熔断节点")
                } catch (_: Exception) {}
            }

            val summary = if (actions.isEmpty()) "AI 巡检通过：节点池运行健康，无需自愈操作" else "AI 自愈完成：" + actions.joinToString("；")
            ResinCoreService.appendLog(summary)
            uiHandler.post {
                Toast.makeText(this, summary, Toast.LENGTH_LONG).show()
                refreshDashboardMetrics()
            }
        }.start()
    }

    private fun switchTab(index: Int) {
        contentContainer.removeAllViews()
        when (index) {
            0 -> buildDashboardTab()
            1 -> buildSubscriptionsAndNodesTab()
            2 -> buildPlatformsAndLeasesTab()
            3 -> buildEndpointsRulesLogsTab()
            4 -> buildAiAndDataSourcesTab()
            5 -> buildWebConsoleTab()
        }
    }

    // =========================================================================
    // Tab 0: 总览、异形屏/屏下摄像头自适应、本地引擎、开机自启与 VpnService 接管
    // =========================================================================
    private fun buildDashboardTab() {
        val scroll = ScrollView(this)
        val col = createColumn()

        // 1. 异形屏与屏下摄像头 (UDC) 自适应显示引擎卡片
        val screenCard = createCard("📱 异形屏 (挖孔/药丸/刘海/曲面/折叠) 与屏下摄像头 (UDC) 自适应")
        val spnScreenMode = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item,
                listOf(
                    "智能自动感应 (自动识别挖孔/刘海/屏下摄像头 UDC)",
                    "屏下摄像头 (UDC) 光学防眩光与消光保护区模式",
                    "异形屏 (挖孔/药丸/刘海/横屏侧边) 增强四向安全避让",
                    "双曲面瀑布屏 / 折叠屏大屏边缘防误触增强模式"
                )
            )
            setSelection(screenAdaptMode.coerceIn(0, 3))
            setBackgroundColor(Color.parseColor("#0F172A"))
        }

        tvScreenDiag = createMonoBox(adaptiveManager.formatDiagnosticsText())

        spnScreenMode.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (screenAdaptMode != position) {
                    screenAdaptMode = position
                    savePrefs()
                    adaptiveManager.recomputeNow(rootLayout) { applyScreenAdaptation(it) }
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        screenCard.addView(createLabel("屏幕形态与摄像头避让策略 (切换后即时生效):"))
        screenCard.addView(spnScreenMode)

        // 顶部安全区高度微调与曲面侧边防误触微调快捷按钮行
        val tuneRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, 0)
        }
        tuneRow.addView(createButton("顶部避让: +${screenExtraTopDp}dp (点击切换)", "#334155") {
            val steps = listOf(0, 6, 12, 18)
            val nextIdx = (steps.indexOf(screenExtraTopDp) + 1) % steps.size
            screenExtraTopDp = steps[nextIdx]
            savePrefs()
            adaptiveManager.recomputeNow(rootLayout) { applyScreenAdaptation(it) }
            switchTab(0)
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        tuneRow.addView(createButton("曲面侧边距: +${screenCurvedEdgeDp}dp (点击切换)", "#334155") {
            val steps = listOf(0, 8, 14, 20)
            val nextIdx = (steps.indexOf(screenCurvedEdgeDp) + 1) % steps.size
            screenCurvedEdgeDp = steps[nextIdx]
            savePrefs()
            adaptiveManager.recomputeNow(rootLayout) { applyScreenAdaptation(it) }
            switchTab(0)
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f) })

        screenCard.addView(tuneRow)
        screenCard.addView(tvScreenDiag)
        col.addView(screenCard)

        // 2. Engine & Boot Auto-Start Card
        val engineCard = createCard("⚙️ 本地网关引擎、开机自启与远程连接配置")
        tvEngineStatus = TextView(this).apply {
            text = "● 正在检测本地 Resin 核心引擎状态..."
            setTextColor(Color.parseColor("#10B981"))
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(6))
        }
        engineCard.addView(tvEngineStatus)

        val chkBoot = CheckBox(this).apply {
            text = "手机开机自动启动本地 Resin 网关引擎 (BOOT_COMPLETED)"
            setTextColor(Color.parseColor("#E2E8F0"))
            isChecked = bootAutoStart
            setOnCheckedChangeListener { _, isChecked ->
                bootAutoStart = isChecked
                savePrefs()
                Toast.makeText(
                    this@MainActivity,
                    if (isChecked) "已开启手机开机自动启动网关" else "已关闭开机自启",
                    Toast.LENGTH_SHORT
                ).show()
            }
        }
        engineCard.addView(chkBoot)

        val inpUrl = createInput(gatewayUrl, "Resin 网关地址 (本地默认 http://127.0.0.1:2260)")
        val inpAdmin = createInput(adminToken, "管理后台密码 RESIN_ADMIN_TOKEN")
        val inpProxy = createInput(proxyToken, "代理认证密码 RESIN_PROXY_TOKEN")
        engineCard.addView(createLabel("网关地址 (支持本地 127.0.0.1:2260 或远程服务器):"))
        engineCard.addView(inpUrl)
        engineCard.addView(createLabel("管理后台密码 (RESIN_ADMIN_TOKEN):"))
        engineCard.addView(inpAdmin)
        engineCard.addView(createLabel("代理接入密码 (RESIN_PROXY_TOKEN):"))
        engineCard.addView(inpProxy)

        val btnRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, 0)
        }
        btnRow.addView(createButton("💾 保存并连接", "#0284C7") {
            gatewayUrl = inpUrl.text.toString().trim().removeSuffix("/")
            adminToken = inpAdmin.text.toString().trim()
            proxyToken = inpProxy.text.toString().trim()
            savePrefs()
            refreshDashboardMetrics()
            Toast.makeText(this, "配置已保存并刷新", Toast.LENGTH_SHORT).show()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        btnRow.addView(createButton("▶ 启动/重启引擎", "#059669") {
            gatewayUrl = inpUrl.text.toString().trim().removeSuffix("/")
            adminToken = inpAdmin.text.toString().trim()
            proxyToken = inpProxy.text.toString().trim()
            stopLocalEngine()
            uiHandler.postDelayed({ startLocalEngine() }, 500)
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        btnRow.addView(createButton("■ 停止", "#DC2626") {
            stopLocalEngine()
        })
        engineCard.addView(btnRow)
        col.addView(engineCard)

        // 3. Android VpnService Per-App Transparent Proxy Card
        val vpnCard = createCard("🛡️ Android VPN 全局 / 分应用透明代理接管 (免 Root)")
        tvVpnStatus = TextView(this).apply {
            text = if (ResinVpnService.isVpnActive()) "🟢 VPN 透明代理隧道: 已开启" else "⚪ VPN 透明代理隧道: 未开启"
            setTextColor(if (ResinVpnService.isVpnActive()) Color.parseColor("#10B981") else Color.parseColor("#94A3B8"))
            textSize = 13.5f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(6))
        }
        vpnCard.addView(tvVpnStatus)

        val spnVpnMode = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item,
                listOf(
                    "全局透明接管模式 (自动排除 Resin 自身防回环)",
                    "分应用白名单模式 (仅下方指定包名应用走 Resin)",
                    "分应用黑名单模式 (排除下方指定包名应用直连)"
                )
            )
            setSelection(vpnAppMode.coerceIn(0, 2))
            setBackgroundColor(Color.parseColor("#0F172A"))
        }
        val inpVpnPkgs = createInput(vpnAppPackages, "分应用包名列表 (逗号分隔，如 com.android.chrome, com.termux)")
        vpnCard.addView(createLabel("流量接管模式:"))
        vpnCard.addView(spnVpnMode)
        vpnCard.addView(createLabel("指定应用包名 (白名单/黑名单模式生效):"))
        vpnCard.addView(inpVpnPkgs)

        val vpnBtnRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, 0)
        }
        vpnBtnRow.addView(createButton("⚡ 开启 VPN 透明代理接管", "#059669") {
            vpnAppMode = spnVpnMode.selectedItemPosition
            vpnAppPackages = inpVpnPkgs.text.toString().trim()
            savePrefs()
            startVpnTakeover()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(8) } })

        vpnBtnRow.addView(createButton("■ 关闭 VPN 接管", "#DC2626") {
            stopVpnTakeover()
        })
        vpnCard.addView(vpnBtnRow)
        col.addView(vpnCard)

        // 4. Live Metrics Snapshot Card
        val metricCard = createCard("📊 节点池健康快照与实时指标")
        tvMetricsSummary = TextView(this).apply {
            text = "正在拉取 Resin 节点池实时指标..."
            setTextColor(Color.parseColor("#E2E8F0"))
            textSize = 13.5f
            setLineSpacing(dp(4).toFloat(), 1.0f)
        }
        metricCard.addView(tvMetricsSummary)

        val metricBtnRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, 0)
        }
        metricBtnRow.addView(createButton("🔄 刷新监控指标", "#334155") {
            refreshDashboardMetrics()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        metricBtnRow.addView(createButton("🩺 AI 巡检与自愈", "#0284C7") {
            runAiAutoHealPatrol()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f) })
        metricCard.addView(metricBtnRow)
        col.addView(metricCard)

        // 5. Quick Copy & Sticky Proxy Workshop
        val proxyCard = createCard("⚡ 粘性代理一键复制与连通性实测")
        val inpTestPlat = createInput("Default", "平台名 Platform")
        val inpTestAcc = createInput("mobile_user_01", "业务粘性账号 Account")
        val tvTestResult = createMonoBox("点击下方按钮可直接复制代理接入地址或测试粘性出口 IP...")

        proxyCard.addView(createLabel("测试平台 (Platform) 与粘性账号 (Account):"))
        proxyCard.addView(inpTestPlat)
        proxyCard.addView(inpTestAcc)

        val copyRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6), 0, dp(6))
        }
        copyRow.addView(createButton("复制 HTTP 代理", "#0284C7") {
            val hostPort = Uri.parse(gatewayUrl).let { "${it.host ?: "127.0.0.1"}:${if (it.port > 0) it.port else 2260}" }
            val id = "${inpTestPlat.text}.${inpTestAcc.text}"
            val proxyStr = "http://$id:$proxyToken@$hostPort"
            copyToClipboard("HTTP 粘性代理", proxyStr)
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        copyRow.addView(createButton("复制 SOCKS5", "#0284C7") {
            val hostPort = Uri.parse(gatewayUrl).let { "${it.host ?: "127.0.0.1"}:${if (it.port > 0) it.port else 2260}" }
            val id = "${inpTestPlat.text}.${inpTestAcc.text}"
            val proxyStr = "socks5h://$id:$proxyToken@$hostPort"
            copyToClipboard("SOCKS5 粘性代理", proxyStr)
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        copyRow.addView(createButton("🚀 实测代理出口", "#059669") {
            val plat = inpTestPlat.text.toString().trim().ifEmpty { "Default" }
            val acc = inpTestAcc.text.toString().trim().ifEmpty { "user1" }
            tvTestResult.text = "正在通过 Resin 反代与正向代理测试出口 IP..."
            Thread {
                val t0 = System.currentTimeMillis()
                val tok = if (proxyToken.isEmpty()) "-" else proxyToken
                val revPath = "/$tok/$plat.$acc/https/api.ipify.org?format=json"
                val (ok, resp) = apiRequest("GET", revPath, null, false)
                val dt = System.currentTimeMillis() - t0
                uiHandler.post {
                    tvTestResult.text = "耗时: ${dt}ms | 状态: ${if (ok) "成功" else "失败"}\n粘性账号: $plat.$acc\n返回出口响应: $resp"
                }
            }.start()
        })
        proxyCard.addView(copyRow)
        proxyCard.addView(tvTestResult)
        col.addView(proxyCard)

        // 6. Core Engine Live Console Logs
        val logCard = createCard("🖥️ 本地 Resin 核心引擎与 AI 自愈实时日志")
        tvCoreLogs = createMonoBox(ResinCoreService.getLogsText())
        logCard.addView(tvCoreLogs)
        col.addView(logCard)

        scroll.addView(col)
        contentContainer.addView(scroll)
        refreshDashboardMetrics()
    }

    private fun refreshDashboardMetrics() {
        Thread {
            val (okHealth, _) = apiRequest("GET", "/healthz", null, false)
            val (okInfo, infoRaw) = apiRequest("GET", "/api/v1/system/info")
            val (okSnap, snapRaw) = apiRequest("GET", "/api/v1/metrics/snapshots/node-pool")
            val (_, tpRaw) = apiRequest("GET", "/api/v1/metrics/realtime/throughput")
            val (_, leaseRaw) = apiRequest("GET", "/api/v1/metrics/realtime/leases")

            val sb = StringBuilder()
            sb.append("网关健康检查 (/healthz): ").append(if (okHealth) "🟢 在线正常" else "🔴 未连接").append("\n")
            if (okInfo) {
                try {
                    val info = JSONObject(infoRaw)
                    sb.append("核心版本: ").append(info.optString("version", "v1.3.1"))
                        .append(" (Commit: ").append(info.optString("git_commit", "-")).append(")\n")
                } catch (_: Exception) {}
            }
            if (okSnap) {
                try {
                    val snap = JSONObject(snapRaw)
                    sb.append("• 全局总节点数: ").append(snap.optInt("total_nodes", 0))
                        .append("  |  🟢 健康可用节点: ").append(snap.optInt("healthy_nodes", 0)).append("\n")
                    sb.append("• 独立出口 IP 数: ").append(snap.optInt("egress_ip_count", 0))
                        .append("  |  🌍 健康独立 IP: ").append(snap.optInt("healthy_egress_ip_count", 0)).append("\n")
                } catch (_: Exception) {}
            }
            try {
                val items = JSONObject(tpRaw).optJSONArray("items")
                if (items != null && items.length() > 0) {
                    val last = items.getJSONObject(items.length() - 1)
                    val inKb = last.optDouble("ingress_bps", 0.0) / 1024.0
                    val outKb = last.optDouble("egress_bps", 0.0) / 1024.0
                    sb.append(String.format(Locale.US, "• 实时吞吐带宽: 上行 %.1f KB/s | 下行 %.1f KB/s\n", inKb, outKb))
                }
            } catch (_: Exception) {}
            try {
                val items = JSONObject(leaseRaw).optJSONArray("items")
                if (items != null && items.length() > 0) {
                    val last = items.getJSONObject(items.length() - 1)
                    sb.append("• 当前活跃账号粘性租约: ").append(last.optInt("active_leases", 0))
                }
            } catch (_: Exception) {}

            uiHandler.post {
                tvMetricsSummary?.text = sb.toString().trim()
            }
        }.start()
    }

    // =========================================================================
    // Tab 1: 订阅源管理与全局节点池探测
    // =========================================================================
    private fun buildSubscriptionsAndNodesTab() {
        val scroll = ScrollView(this)
        val col = createColumn()

        val addSubCard = createCard("➕ 添加代理节点订阅 (远程 URL 或本地粘贴节点)")
        val inpSubName = createInput("", "订阅名称 (例如: 主力专线 / 静态住宅池)")
        val inpSubUrl = createInput("", "远程订阅 URL (http:// 或 https://，本地订阅可留空)")
        val inpSubContent = createInput("", "本地节点内容 (URI行/IP:PORT/Clash/Sing-box，远程可留空)").apply {
            minLines = 3
            maxLines = 6
            isSingleLine = false
        }
        val spnChainRole = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item,
                listOf("普通直出节点", "链式落地节点 (chain_proxy)", "链式跳板节点 (chain_relay)")
            )
            setBackgroundColor(Color.parseColor("#0F172A"))
        }

        addSubCard.addView(inpSubName)
        addSubCard.addView(inpSubUrl)
        addSubCard.addView(inpSubContent)
        addSubCard.addView(createLabel("链式代理角色:"))
        addSubCard.addView(spnChainRole)

        val tvSubsList = createMonoBox("正在加载订阅列表...")
        addSubCard.addView(createButton("➕ 创建订阅并立即同步节点", "#059669") {
            val name = inpSubName.text.toString().trim()
            val url = inpSubUrl.text.toString().trim()
            val content = inpSubContent.text.toString().trim()
            if (name.isEmpty()) {
                Toast.makeText(this, "请填写订阅名称", Toast.LENGTH_SHORT).show()
                return@createButton
            }
            val isLocal = url.isEmpty() && content.isNotEmpty()
            val roleIdx = spnChainRole.selectedItemPosition
            val payload = JSONObject().apply {
                put("name", name)
                put("source_type", if (isLocal) "local" else "remote")
                if (isLocal) put("content", content) else put("url", url)
                put("update_interval", "30m")
                put("enabled", true)
                put("chain_proxy", roleIdx == 1)
                put("chain_relay", roleIdx == 2)
            }
            Thread {
                val (ok, resp) = apiRequest("POST", "/api/v1/subscriptions", payload.toString())
                if (ok) {
                    try {
                        val subId = JSONObject(resp).optString("id", "")
                        if (subId.isNotEmpty()) {
                            apiRequest("POST", "/api/v1/subscriptions/$subId/actions/refresh", "{}")
                        }
                    } catch (_: Exception) {}
                }
                uiHandler.post {
                    Toast.makeText(this, if (ok) "订阅创建并刷新成功" else "创建失败: $resp", Toast.LENGTH_LONG).show()
                    loadSubsAndNodesInto(tvSubsList, null)
                }
            }.start()
        }.apply {
            val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            lp.topMargin = dp(8)
            layoutParams = lp
        })
        col.addView(addSubCard)

        val subListCard = createCard("📡 已配置订阅源列表与一键刷新/清理")
        val inpTargetSubId = createInput("", "输入或粘贴订阅 ID 执行刷新 / 清理熔断 / 删除")
        val subBtnRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        subBtnRow.addView(createButton("🔄 刷新全部", "#0284C7") {
            loadSubsAndNodesInto(tvSubsList, null, refreshAll = true)
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        subBtnRow.addView(createButton("🧹 清理熔断", "#334155") {
            val sid = inpTargetSubId.text.toString().trim()
            if (sid.isNotEmpty()) {
                Thread {
                    val (_, r) = apiRequest("POST", "/api/v1/subscriptions/$sid/actions/cleanup-circuit-open-nodes", "{}")
                    uiHandler.post {
                        Toast.makeText(this, "清理结果: $r", Toast.LENGTH_LONG).show()
                        loadSubsAndNodesInto(tvSubsList, null)
                    }
                }.start()
            }
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        subBtnRow.addView(createButton("🗑 删除订阅", "#DC2626") {
            val sid = inpTargetSubId.text.toString().trim()
            if (sid.isNotEmpty()) {
                Thread {
                    apiRequest("DELETE", "/api/v1/subscriptions/$sid")
                    uiHandler.post { loadSubsAndNodesInto(tvSubsList, null) }
                }.start()
            }
        })
        subListCard.addView(inpTargetSubId)
        subListCard.addView(subBtnRow)
        subListCard.addView(tvSubsList)
        col.addView(subListCard)

        val nodeCard = createCard("🌐 全局节点池检索与主动出口/延迟探测")
        val inpNodeFilter = createInput("", "按标签关键字或地区筛选 (如: 香港, hk, us)")
        val inpNodeHash = createInput("", "输入节点 Hash 执行同步出口 IP 探测 / 权威延迟探测")
        val tvNodesList = createMonoBox("正在加载全局节点池...")

        val nodeBtnRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        nodeBtnRow.addView(createButton("🔍 检索节点", "#0284C7") {
            loadSubsAndNodesInto(null, tvNodesList, tagFilter = inpNodeFilter.text.toString().trim())
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        nodeBtnRow.addView(createButton("🌍 探测出口 IP", "#059669") {
            val h = inpNodeHash.text.toString().trim()
            if (h.isNotEmpty()) {
                Thread {
                    val (_, r) = apiRequest("POST", "/api/v1/nodes/$h/actions/probe-egress", "{}")
                    uiHandler.post {
                        Toast.makeText(this, "出口探测: $r", Toast.LENGTH_LONG).show()
                        loadSubsAndNodesInto(null, tvNodesList)
                    }
                }.start()
            }
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        nodeBtnRow.addView(createButton("⚡ 探测延迟", "#334155") {
            val h = inpNodeHash.text.toString().trim()
            if (h.isNotEmpty()) {
                Thread {
                    val (_, r) = apiRequest("POST", "/api/v1/nodes/$h/actions/probe-latency", "{}")
                    uiHandler.post {
                        Toast.makeText(this, "延迟探测: $r", Toast.LENGTH_LONG).show()
                        loadSubsAndNodesInto(null, tvNodesList)
                    }
                }.start()
            }
        })
        nodeCard.addView(inpNodeFilter)
        nodeCard.addView(inpNodeHash)
        nodeCard.addView(nodeBtnRow)
        nodeCard.addView(tvNodesList)
        col.addView(nodeCard)

        scroll.addView(col)
        contentContainer.addView(scroll)
        loadSubsAndNodesInto(tvSubsList, tvNodesList)
    }

    private fun loadSubsAndNodesInto(
        tvSubs: TextView?,
        tvNodes: TextView?,
        refreshAll: Boolean = false,
        tagFilter: String = ""
    ) {
        Thread {
            if (tvSubs != null) {
                val (ok, raw) = apiRequest("GET", "/api/v1/subscriptions?limit=100&offset=0")
                val sb = StringBuilder()
                if (ok) {
                    try {
                        val items = JSONObject(raw).optJSONArray("items") ?: JSONArray()
                        if (refreshAll) {
                            for (i in 0 until items.length()) {
                                val sid = items.getJSONObject(i).optString("id")
                                apiRequest("POST", "/api/v1/subscriptions/$sid/actions/refresh", "{}")
                            }
                        }
                        sb.append("共 ").append(items.length()).append(" 个订阅源:\n")
                        for (i in 0 until items.length()) {
                            val s = items.getJSONObject(i)
                            sb.append("• [").append(s.optString("name")).append("] ID: ").append(s.optString("id")).append("\n")
                            sb.append("  节点: ").append(s.optInt("node_count")).append(" (健康: ").append(s.optInt("healthy_node_count")).append(") | 周期: ").append(s.optString("update_interval")).append("\n")
                            if (s.optString("last_error").isNotEmpty()) {
                                sb.append("  ⚠️ 错误: ").append(s.optString("last_error")).append("\n")
                            }
                        }
                    } catch (e: Exception) {
                        sb.append("解析失败: ").append(e.message)
                    }
                } else {
                    sb.append("拉取订阅失败: ").append(raw)
                }
                uiHandler.post { tvSubs.text = sb.toString().trim() }
            }

            if (tvNodes != null) {
                var path = "/api/v1/nodes?limit=80&offset=0"
                if (tagFilter.isNotEmpty()) {
                    path += "&tag_keyword=" + URLEncoder.encode(tagFilter, "UTF-8")
                }
                val (ok, raw) = apiRequest("GET", path)
                val sb = StringBuilder()
                if (ok) {
                    try {
                        val obj = JSONObject(raw)
                        val items = obj.optJSONArray("items") ?: JSONArray()
                        sb.append("匹配节点: ").append(obj.optInt("total", items.length()))
                            .append(" | 独立出口 IP: ").append(obj.optInt("unique_egress_ips", 0)).append("\n\n")
                        for (i in 0 until items.length()) {
                            val n = items.getJSONObject(i)
                            val hash = n.optString("node_hash")
                            val circuit = if (n.isNull("circuit_open_since")) "🟢" else "🔴熔断"
                            val lat = if (n.has("reference_latency_ms")) "${n.optDouble("reference_latency_ms").toInt()}ms" else "-"
                            sb.append(circuit).append(" [").append(n.optString("region", "?")).append("] ")
                                .append(n.optString("display_tag", hash.take(10))).append("\n")
                            sb.append("   Hash: ").append(hash).append("\n")
                            sb.append("   出口IP: ").append(n.optString("egress_ip", "-")).append(" | 延迟: ").append(lat)
                                .append(" | 失败: ").append(n.optInt("failure_count", 0)).append("\n")
                        }
                    } catch (e: Exception) {
                        sb.append("解析节点失败: ").append(e.message)
                    }
                } else {
                    sb.append("获取节点失败: ").append(raw)
                }
                uiHandler.post { tvNodes.text = sb.toString().trim() }
            }
        }.start()
    }

    // =========================================================================
    // Tab 2: 平台隔离池与粘性租约管理
    // =========================================================================
    private fun buildPlatformsAndLeasesTab() {
        val scroll = ScrollView(this)
        val col = createColumn()

        val platCard = createCard("🎯 Platform 隔离池管理与新建")
        val inpPlatName = createInput("", "新平台名称 (例如: US_Sticky_Pool)")
        val inpPlatRegions = createInput("us,hk,jp,sg", "地区过滤代码 (逗号分隔，如 us,hk)")
        val inpPlatRegex = createInput("", "节点标签正则表达式 (逗号分隔，如 香港|美国,*专线,!过期)")
        val inpPlatTtl = createInput("168h", "粘性会话保持时间 (Sticky TTL，例如 168h)")
        val tvPlats = createMonoBox("正在加载平台列表...")

        platCard.addView(inpPlatName)
        platCard.addView(inpPlatRegions)
        platCard.addView(inpPlatRegex)
        platCard.addView(inpPlatTtl)
        platCard.addView(createButton("➕ 创建新 Platform 隔离池", "#059669") {
            val name = inpPlatName.text.toString().trim()
            if (name.isEmpty()) return@createButton
            val regions = JSONArray(inpPlatRegions.text.toString().split(",").map { it.trim().lowercase() }.filter { it.isNotEmpty() })
            val regexes = JSONArray(inpPlatRegex.text.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() })
            val body = JSONObject().apply {
                put("name", name)
                put("sticky_ttl", inpPlatTtl.text.toString().trim().ifEmpty { "168h" })
                put("region_filters", regions)
                put("regex_filters", regexes)
                put("allocation_policy", "BALANCED")
            }
            Thread {
                val (ok, r) = apiRequest("POST", "/api/v1/platforms", body.toString())
                uiHandler.post {
                    Toast.makeText(this, if (ok) "平台创建成功" else "创建失败: $r", Toast.LENGTH_LONG).show()
                    loadPlatformsAndLeases(tvPlats, null)
                }
            }.start()
        })
        platCard.addView(tvPlats)
        col.addView(platCard)

        val leaseCard = createCard("🔗 活跃账号粘性租约、出口 IP 负载与租约继承")
        val inpLeasePlatId = createInput("", "平台 ID (留空默认查询第一个平台 Default)")
        val inpParentAcc = createInput("", "父账号 (Parent Account)")
        val inpChildAcc = createInput("", "新子账号 (New Account)")
        val tvLeases = createMonoBox("正在加载活跃租约与出口 IP 负载...")

        val leaseBtnRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        leaseBtnRow.addView(createButton("🔄 刷新租约与负载", "#0284C7") {
            loadPlatformsAndLeases(tvPlats, tvLeases, inpLeasePlatId.text.toString().trim())
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        leaseBtnRow.addView(createButton("🧬 执行租约继承", "#059669") {
            val pAcc = inpParentAcc.text.toString().trim()
            val nAcc = inpChildAcc.text.toString().trim()
            if (pAcc.isNotEmpty() && nAcc.isNotEmpty()) {
                Thread {
                    val tok = proxyToken.ifEmpty { "my-token" }
                    val body = JSONObject().put("parent_account", pAcc).put("new_account", nAcc).toString()
                    val (ok, r) = apiRequest("POST", "/$tok/api/v1/Default/actions/inherit-lease", body)
                    uiHandler.post {
                        Toast.makeText(this, if (ok) "租约继承成功" else "失败: $r", Toast.LENGTH_LONG).show()
                        loadPlatformsAndLeases(tvPlats, tvLeases, inpLeasePlatId.text.toString().trim())
                    }
                }.start()
            }
        })

        leaseCard.addView(inpLeasePlatId)
        leaseCard.addView(inpParentAcc)
        leaseCard.addView(inpChildAcc)
        leaseCard.addView(leaseBtnRow)
        leaseCard.addView(tvLeases)
        col.addView(leaseCard)

        scroll.addView(col)
        contentContainer.addView(scroll)
        loadPlatformsAndLeases(tvPlats, tvLeases)
    }

    private fun loadPlatformsAndLeases(tvPlats: TextView?, tvLeases: TextView?, targetPlatId: String = "") {
        Thread {
            val (ok, raw) = apiRequest("GET", "/api/v1/platforms?limit=100&offset=0")
            var firstPlatId = targetPlatId
            val sbP = StringBuilder()
            if (ok) {
                try {
                    val items = JSONObject(raw).optJSONArray("items") ?: JSONArray()
                    for (i in 0 until items.length()) {
                        val p = items.getJSONObject(i)
                        if (firstPlatId.isEmpty()) firstPlatId = p.optString("id")
                        sbP.append("• [").append(p.optString("name")).append("] 可路由节点: ")
                            .append(p.optInt("routable_node_count")).append(" | TTL: ").append(p.optString("sticky_ttl")).append("\n")
                        sbP.append("  ID: ").append(p.optString("id")).append(" | 策略: ").append(p.optString("allocation_policy")).append("\n")
                    }
                } catch (_: Exception) {}
            }
            uiHandler.post { tvPlats?.text = sbP.toString().trim().ifEmpty { "暂无平台数据" } }

            if (tvLeases != null && firstPlatId.isNotEmpty()) {
                val (okL, rawL) = apiRequest("GET", "/api/v1/platforms/$firstPlatId/leases?limit=100&offset=0")
                val (okIp, rawIp) = apiRequest("GET", "/api/v1/platforms/$firstPlatId/ip-load?limit=50&offset=0")
                val sbL = StringBuilder()
                if (okL) {
                    try {
                        val items = JSONObject(rawL).optJSONArray("items") ?: JSONArray()
                        sbL.append("=== 活跃粘性租约 (").append(items.length()).append(") ===\n")
                        for (i in 0 until items.length()) {
                            val l = items.getJSONObject(i)
                            sbL.append("• 账号: ").append(l.optString("account")).append(" -> 出口IP: ")
                                .append(l.optString("egress_ip")).append(" (").append(l.optString("node_tag")).append(")\n")
                        }
                    } catch (_: Exception) {}
                }
                if (okIp) {
                    try {
                        val items = JSONObject(rawIp).optJSONArray("items") ?: JSONArray()
                        sbL.append("\n=== 出口 IP 负载统计 ===\n")
                        for (i in 0 until items.length()) {
                            val e = items.getJSONObject(i)
                            sbL.append("• IP: ").append(e.optString("egress_ip")).append(" -> 绑定租约数: ")
                                .append(e.optInt("lease_count")).append("\n")
                        }
                    } catch (_: Exception) {}
                }
                uiHandler.post { tvLeases.text = sbL.toString().trim() }
            }
        }.start()
    }

    // =========================================================================
    // Tab 3: 多接入点、请求头提取规则、结构化日志与 GeoIP
    // =========================================================================
    private fun buildEndpointsRulesLogsTab() {
        val scroll = ScrollView(this)
        val col = createColumn()

        val epCard = createCard("🔌 多接入点端口管理 (/api/v1/endpoints)")
        val inpNewPort = createInput("2300", "新监听端口号 (1-65535)").apply {
            inputType = InputType.TYPE_CLASS_NUMBER
        }
        val tvEndpoints = createMonoBox("正在加载接入点列表...")
        epCard.addView(inpNewPort)
        epCard.addView(createButton("➕ 热添加代理监听端口 (HTTP正向+反代+SOCKS5)", "#059669") {
            val portNum = inpNewPort.text.toString().toIntOrNull() ?: 2300
            val body = JSONObject().apply {
                put("port", portNum)
                put("enabled", true)
                put("allow_management", false)
                put("allow_proxy", true)
                put("allow_http_forward", true)
                put("allow_http_reverse", true)
                put("allow_socks5", true)
            }
            Thread {
                val (ok, r) = apiRequest("POST", "/api/v1/endpoints", body.toString())
                uiHandler.post {
                    Toast.makeText(this, if (ok) "端口 $portNum 添加成功" else "添加失败: $r", Toast.LENGTH_LONG).show()
                    loadEndpointsRulesLogs(tvEndpoints, null, null)
                }
            }.start()
        })
        epCard.addView(tvEndpoints)
        col.addView(epCard)

        val ruleCard = createCard("📑 请求头账号提取规则 (/api/v1/account-header-rules)")
        val inpPrefix = createInput("api.openai.com/v1", "URL 前缀 (如 api.openai.com/v1)")
        val inpHeaders = createInput("Authorization,x-api-key", "提取请求头列表 (逗号分隔)")
        val tvRules = createMonoBox("正在加载请求头提取规则...")
        ruleCard.addView(inpPrefix)
        ruleCard.addView(inpHeaders)
        ruleCard.addView(createButton("💾 保存 URL 前缀提取规则", "#0284C7") {
            val prefix = inpPrefix.text.toString().trim().removePrefix("/")
            val hdrs = JSONArray(inpHeaders.text.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() })
            Thread {
                val (ok, r) = apiRequest("PUT", "/api/v1/account-header-rules/$prefix", JSONObject().put("headers", hdrs).toString())
                uiHandler.post {
                    Toast.makeText(this, if (ok) "规则已保存" else "失败: $r", Toast.LENGTH_SHORT).show()
                    loadEndpointsRulesLogs(null, tvRules, null)
                }
            }.start()
        })
        ruleCard.addView(tvRules)
        col.addView(ruleCard)

        val logCard = createCard("📜 最近结构化请求日志 & GeoIP 查询")
        val inpGeoIp = createInput("1.1.1.1", "输入 IP 查询 GeoIP 国家/地区代码")
        val tvReqLogs = createMonoBox("正在加载最近请求日志...")
        val geoRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        geoRow.addView(createButton("🌍 查询 IP 归属地", "#0284C7") {
            val ip = inpGeoIp.text.toString().trim()
            Thread {
                val (_, r) = apiRequest("GET", "/api/v1/geoip/lookup?ip=$ip")
                uiHandler.post { Toast.makeText(this, "GeoIP: $r", Toast.LENGTH_LONG).show() }
            }.start()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        geoRow.addView(createButton("🔄 更新 GeoIP 库", "#334155") {
            Thread {
                val (_, r) = apiRequest("POST", "/api/v1/geoip/actions/update-now", "{}")
                uiHandler.post { Toast.makeText(this, "GeoIP 更新: $r", Toast.LENGTH_LONG).show() }
            }.start()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        geoRow.addView(createButton("刷新日志", "#059669") {
            loadEndpointsRulesLogs(null, null, tvReqLogs)
        })
        logCard.addView(inpGeoIp)
        logCard.addView(geoRow)
        logCard.addView(tvReqLogs)
        col.addView(logCard)

        scroll.addView(col)
        contentContainer.addView(scroll)
        loadEndpointsRulesLogs(tvEndpoints, tvRules, tvReqLogs)
    }

    private fun loadEndpointsRulesLogs(tvEp: TextView?, tvRules: TextView?, tvLogs: TextView?) {
        Thread {
            if (tvEp != null) {
                val (ok, raw) = apiRequest("GET", "/api/v1/endpoints?limit=50&offset=0")
                val sb = StringBuilder()
                if (ok) {
                    try {
                        val items = JSONObject(raw).optJSONArray("items") ?: JSONArray()
                        for (i in 0 until items.length()) {
                            val ep = items.getJSONObject(i)
                            sb.append("• 端口 ").append(ep.optInt("port")).append(" [").append(ep.optString("status")).append("] ")
                                .append("管理:").append(if (ep.optBoolean("allow_management")) "开" else "关")
                                .append(" HTTP:").append(if (ep.optBoolean("allow_http_forward")) "开" else "关")
                                .append(" 反代:").append(if (ep.optBoolean("allow_http_reverse")) "开" else "关")
                                .append(" SOCKS5:").append(if (ep.optBoolean("allow_socks5")) "开" else "关").append("\n")
                        }
                    } catch (_: Exception) {}
                }
                uiHandler.post { tvEp.text = sb.toString().trim().ifEmpty { "无接入点数据" } }
            }
            if (tvRules != null) {
                val (ok, raw) = apiRequest("GET", "/api/v1/account-header-rules?limit=50&offset=0")
                val sb = StringBuilder()
                if (ok) {
                    try {
                        val items = JSONObject(raw).optJSONArray("items") ?: JSONArray()
                        for (i in 0 until items.length()) {
                            val r = items.getJSONObject(i)
                            sb.append("• 前缀: ").append(r.optString("url_prefix")).append(" -> Headers: ")
                                .append(r.optJSONArray("headers")?.join(", ")).append("\n")
                        }
                    } catch (_: Exception) {}
                }
                uiHandler.post { tvRules.text = sb.toString().trim().ifEmpty { "无规则数据" } }
            }
            if (tvLogs != null) {
                val (ok, raw) = apiRequest("GET", "/api/v1/request-logs?limit=30")
                val sb = StringBuilder()
                if (ok) {
                    try {
                        val items = JSONObject(raw).optJSONArray("items") ?: JSONArray()
                        sb.append("最近 ").append(items.length()).append(" 条请求审计日志:\n")
                        for (i in 0 until items.length()) {
                            val l = items.getJSONObject(i)
                            sb.append("• [").append(l.optString("platform_name")).append("/").append(l.optString("account", "-")).append("] ")
                                .append(l.optString("http_method")).append(" ").append(l.optString("target_host"))
                                .append(" -> HTTP ").append(l.optInt("http_status")).append(" (").append(l.optLong("duration_ms")).append("ms, IP: ")
                                .append(l.optString("egress_ip", "-")).append(")\n")
                        }
                    } catch (_: Exception) {}
                }
                uiHandler.post { tvLogs.text = sb.toString().trim().ifEmpty { "暂无请求日志" } }
            }
        }.start()
    }

    // =========================================================================
    // Tab 4: AI 智能代理助手、自动巡检自愈、数据源 API 中心与自动更新
    // =========================================================================
    private fun buildAiAndDataSourcesTab() {
        val scroll = ScrollView(this)
        val col = createColumn()

        val aiCard = createCard("🤖 大模型 API 配置、AI 节点池自愈与规则生成助手")
        val inpBase = createInput(llmBaseUrl, "API Base URL (支持 DeepSeek/通义千问/OpenAI/局域网 Ollama)")
        val inpMod = createInput(llmModel, "模型名称 (如 deepseek-chat, qwen-plus, qwen2.5:7b)")
        val inpKey = createInput(llmApiKey, "API Key (本地 Ollama/LM Studio 可留空)")
        val inpPrompt = createInput("请帮我编写筛选香港、新加坡、日本低延迟专线节点并排除过期节点的 Resin Platform 正则过滤规则。", "输入 AI 提问...")
        val tvAiOut = createMonoBox("点击下方按钮执行 AI 节点池自愈巡检、生成 Platform 过滤规则或业务接入代码...")

        aiCard.addView(createLabel("大模型 API Base URL:"))
        aiCard.addView(inpBase)
        aiCard.addView(createLabel("模型名称 (Model):"))
        aiCard.addView(inpMod)
        aiCard.addView(createLabel("API Key (可选):"))
        aiCard.addView(inpKey)
        aiCard.addView(createLabel("向 Resin AI 助手提问:"))
        aiCard.addView(inpPrompt)

        val aiBtnRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, dp(8))
        }
        aiBtnRow.addView(createButton("✨ 发送提问 / 生成规则", "#059669") {
            llmBaseUrl = inpBase.text.toString().trim().removeSuffix("/")
            llmModel = inpMod.text.toString().trim()
            llmApiKey = inpKey.text.toString().trim()
            savePrefs()
            val q = inpPrompt.text.toString().trim()
            tvAiOut.text = "🤖 正在思考并生成方案..."
            Thread {
                val ans = callLlmOrFallback(q)
                uiHandler.post { tvAiOut.text = ans }
            }.start()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        aiBtnRow.addView(createButton("🩺 AI 自愈巡检", "#0284C7") {
            runAiAutoHealPatrol()
        })
        aiCard.addView(aiBtnRow)
        aiCard.addView(tvAiOut)
        col.addView(aiCard)

        val dsCard = createCard("🗄️ 数据源 API 连通性中心 & GitHub Release 更新检查")
        val tvDsOut = createMonoBox(
            "内置数据源清单:\n" +
                "1. Resin 控制面: $gatewayUrl/healthz\n" +
                "2. 延迟探测源: https://www.gstatic.com/generate_204\n" +
                "3. Cloudflare 出口探测: https://www.cloudflare.com/cdn-cgi/trace\n" +
                "4. DNSPod DoH: https://doh.pub/dns-query\n" +
                "5. AliDNS DoH: https://dns.alidns.com/dns-query\n" +
                "6. Ipify 出口校验: https://api.ipify.org?format=json"
        )
        val dsBtnRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        dsBtnRow.addView(createButton("⚡ 测试全部数据源", "#0284C7") {
            tvDsOut.text = "正在并发探测全部数据源端点..."
            Thread {
                val urls = listOf(
                    "Resin 控制面" to "$gatewayUrl/healthz",
                    "Google 204 延迟探测" to "https://www.gstatic.com/generate_204",
                    "Cloudflare Trace" to "https://www.cloudflare.com/cdn-cgi/trace",
                    "Ipify 公网 IP" to "https://api.ipify.org?format=json"
                )
                val sb = StringBuilder()
                for ((name, u) in urls) {
                    val t0 = System.currentTimeMillis()
                    val code = try {
                        val conn = URL(u).openConnection() as HttpURLConnection
                        conn.connectTimeout = 5000
                        conn.readTimeout = 5000
                        conn.responseCode
                    } catch (e: Exception) {
                        -1
                    }
                    val dt = System.currentTimeMillis() - t0
                    sb.append(if (code in 200..399) "🟢 " else "🔴 ").append(name)
                        .append(": HTTP ").append(code).append(" (").append(dt).append(" ms)\n")
                }
                uiHandler.post { tvDsOut.text = sb.toString().trim() }
            }.start()
        }.apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { rightMargin = dp(6) } })

        dsBtnRow.addView(createButton("🔄 检查 GitHub 更新", "#059669") {
            tvDsOut.text = "正在查询 gouqizi2214730-source/Resin 最新 Release..."
            Thread {
                try {
                    val conn = URL("https://api.github.com/repos/gouqizi2214730-source/Resin/releases/latest").openConnection() as HttpURLConnection
                    conn.setRequestProperty("Accept", "application/vnd.github+json")
                    conn.setRequestProperty("User-Agent", "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)")
                    val raw = conn.inputStream.bufferedReader().readText()
                    val rel = JSONObject(raw)
                    val tag = rel.optString("tag_name", "v1.3.1")
                    val htmlUrl = rel.optString("html_url", "https://github.com/gouqizi2214730-source/Resin/releases")
                    uiHandler.post {
                        tvDsOut.text = "最新 GitHub Release: $tag\n当前版本: v1.3.1\n发布页面: $htmlUrl"
                    }
                } catch (e: Exception) {
                    uiHandler.post { tvDsOut.text = "检查更新异常: ${e.message}" }
                }
            }.start()
        })

        dsCard.addView(dsBtnRow)
        dsCard.addView(tvDsOut)
        col.addView(dsCard)

        scroll.addView(col)
        contentContainer.addView(scroll)
    }

    // =========================================================================
    // Tab 5: 内置完整 React WebUI 控制台 (WebView + 异形屏 Safe-Area CSS 注入)
    // =========================================================================
    @SuppressLint("SetJavaScriptEnabled")
    private fun buildWebConsoleTab() {
        val wrapper = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(Color.parseColor("#1E293B"))
            setPadding(dp(10), dp(6), dp(10), dp(6))
        }
        val tvUrl = TextView(this).apply {
            text = "WebUI: $gatewayUrl/ui/ (已适配异形屏安全区)"
            setTextColor(Color.parseColor("#94A3B8"))
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val btnReload = createButton("🔄 刷新面板", "#0284C7") {
            webViewInstance?.reload()
        }
        bar.addView(tvUrl)
        bar.addView(btnReload)
        wrapper.addView(bar)

        val wv = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = true
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    val prof = adaptiveManager.currentProfile
                    val safeBotDp = if (prof != null) (prof.safeBottomPx / prof.density).toInt() else 16
                    val safeEdgeDp = if (prof != null) (prof.safeLeftPx / prof.density).toInt() else 0
                    val js = """
                        try {
                            if ('$adminToken') {
                                localStorage.setItem('resin_admin_token', '$adminToken');
                                sessionStorage.setItem('resin_admin_token', '$adminToken');
                            }
                            document.documentElement.style.setProperty('--safe-bottom', '${safeBotDp}px');
                            document.body.style.paddingBottom = '${safeBotDp}px';
                            document.body.style.paddingLeft = '${safeEdgeDp}px';
                            document.body.style.paddingRight = '${safeEdgeDp}px';
                        } catch(e) {}
                    """.trimIndent()
                    view?.evaluateJavascript(js, null)
                }
            }
            loadUrl("$gatewayUrl/ui/")
        }
        webViewInstance = wv
        wrapper.addView(wv)
        contentContainer.addView(wrapper)
    }

    // =========================================================================
    // HTTP Client & LLM Helper
    // =========================================================================
    private fun apiRequest(
        method: String,
        path: String,
        jsonBody: String? = null,
        useAdminAuth: Boolean = true
    ): Pair<Boolean, String> {
        return try {
            val fullUrl = if (path.startsWith("http")) path else "$gatewayUrl$path"
            val conn = URL(fullUrl).openConnection() as HttpURLConnection
            conn.requestMethod = method
            conn.connectTimeout = 10000
            conn.readTimeout = 15000
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("User-Agent", "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)")
            if (useAdminAuth && adminToken.isNotEmpty()) {
                conn.setRequestProperty("Authorization", "Bearer $adminToken")
            }
            if (jsonBody != null && method in listOf("POST", "PUT", "PATCH")) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8")
                OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(jsonBody) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val respText = stream?.bufferedReader(Charsets.UTF_8)?.use(BufferedReader::readText) ?: ""
            Pair(code in 200..299, respText.ifEmpty { "{\"status\":\"ok\",\"code\":$code}" })
        } catch (e: Exception) {
            Pair(false, "网络异常: ${e.message}")
        }
    }

    private fun callLlmOrFallback(prompt: String): String {
        if (llmApiKey.isNotEmpty() || llmBaseUrl.contains("11434") || llmBaseUrl.contains("1234")) {
            try {
                val conn = URL("$llmBaseUrl/chat/completions").openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.connectTimeout = 15000
                conn.readTimeout = 25000
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8")
                if (llmApiKey.isNotEmpty()) {
                    conn.setRequestProperty("Authorization", "Bearer $llmApiKey")
                }
                val body = JSONObject().apply {
                    put("model", llmModel)
                    put("temperature", 0.3)
                    put("messages", JSONArray().apply {
                        put(JSONObject().put("role", "system").put("content", "你是 Resin 智能代理池网关架构专家。"))
                        put(JSONObject().put("role", "user").put("content", prompt))
                    })
                }
                OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
                if (conn.responseCode in 200..299) {
                    val resp = JSONObject(conn.inputStream.bufferedReader().readText())
                    return resp.getJSONArray("choices").getJSONObject(0)
                        .getJSONObject("message").getString("content")
                }
            } catch (_: Exception) {}
        }
        return """
            【Resin 内置智能专家方案】
            1. Platform 地区过滤 (region_filters):
               hk, sg, jp, us
            2. 节点标签正则过滤 (regex_filters):
               (?i)(香港|HK|新加坡|SG|日本|JP)
               *(?i)(专线|IEPL|IPLC|BGP|高速)
               !(?i)(过期|剩余|流量|官网|测试)
            3. 粘性会话正向代理接入:
               curl -x $gatewayUrl -U "Default.user_01:$proxyToken" https://api.ipify.org
            4. 粘性会话反向代理接入 (推荐生产环境使用 X-Resin-Account):
               curl "$gatewayUrl/$proxyToken/Default/https/api.ipify.org" -H "X-Resin-Account: user_01"
        """.trimIndent()
    }

    // =========================================================================
    // UI Helpers
    // =========================================================================
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun roundedBg(hexColor: String, radiusPx: Int, strokeHex: String? = null): GradientDrawable {
        return GradientDrawable().apply {
            setColor(Color.parseColor(hexColor))
            cornerRadius = radiusPx.toFloat()
            if (strokeHex != null) {
                setStroke(dp(1), Color.parseColor(strokeHex))
            }
        }
    }

    private fun createColumn(): LinearLayout {
        val prof = adaptiveManager.currentProfile
        val hPad = if (prof?.isFoldableOrTablet == true) dp(24) else dp(12)
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(hPad, dp(12), hPad, dp(24))
        }
    }

    private fun createCard(title: String): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedBg("#1E293B", dp(10), "#334155")
            setPadding(dp(14), dp(12), dp(14), dp(14))
            val lp = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            lp.bottomMargin = dp(12)
            layoutParams = lp

            val tv = TextView(this@MainActivity).apply {
                text = title
                setTextColor(Color.parseColor("#38BDF8"))
                textSize = 15f
                setTypeface(typeface, Typeface.BOLD)
                setPadding(0, 0, 0, dp(8))
            }
            addView(tv)
        }
    }

    private fun createLabel(textStr: String): TextView {
        return TextView(this).apply {
            text = textStr
            setTextColor(Color.parseColor("#94A3B8"))
            textSize = 12.5f
            setPadding(0, dp(4), 0, dp(2))
        }
    }

    private fun createInput(defaultText: String, hintText: String): EditText {
        return EditText(this).apply {
            setText(defaultText)
            hint = hintText
            setTextColor(Color.parseColor("#F8FAFC"))
            setHintTextColor(Color.parseColor("#64748B"))
            textSize = 13.5f
            background = roundedBg("#0F172A", dp(6), "#334155")
            setPadding(dp(10), dp(8), dp(10), dp(8))
            isSingleLine = true
            val lp = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            lp.topMargin = dp(4)
            lp.bottomMargin = dp(4)
            layoutParams = lp
        }
    }

    private fun createButton(label: String, bgHex: String, onClick: () -> Unit): Button {
        return Button(this).apply {
            text = label
            setTextColor(Color.WHITE)
            textSize = 13f
            isAllCaps = false
            background = roundedBg(bgHex, dp(6))
            setPadding(dp(12), dp(6), dp(12), dp(6))
            setOnClickListener { onClick() }
        }
    }

    private fun createMonoBox(initialText: String): TextView {
        return TextView(this).apply {
            text = initialText
            setTextColor(Color.parseColor("#E2E8F0"))
            textSize = 12f
            typeface = Typeface.MONOSPACE
            background = roundedBg("#0F172A", dp(6), "#334155")
            setPadding(dp(10), dp(10), dp(10), dp(10))
            setTextIsSelectable(true)
            val lp = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            lp.topMargin = dp(8)
            layoutParams = lp
        }
    }

    private fun copyToClipboard(label: String, text: String) {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText(label, text))
        Toast.makeText(this, "已复制 $label: $text", Toast.LENGTH_LONG).show()
    }

    override fun onDestroy() {
        uiHandler.removeCallbacks(logRefreshRunnable)
        super.onDestroy()
    }
}
