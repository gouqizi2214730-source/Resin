package com.resinat.resin.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CopyOnWriteArrayList

class ResinCoreService : Service() {

    companion object {
        const val CHANNEL_ID = "resin_core_gateway_channel"
        const val NOTIFICATION_ID = 2260
        const val ACTION_START = "com.resinat.resin.android.ACTION_START"
        const val ACTION_STOP = "com.resinat.resin.android.ACTION_STOP"

        @Volatile
        var coreProcess: Process? = null

        val logLines = CopyOnWriteArrayList<String>()

        fun isRunning(): Boolean {
            val p = coreProcess ?: return false
            return try {
                p.exitValue()
                false
            } catch (e: IllegalThreadStateException) {
                true
            }
        }

        fun appendLog(msg: String) {
            val ts = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
            logLines.add("[$ts] $msg")
            while (logLines.size > 350) {
                logLines.removeAt(0)
            }
        }

        fun getLogsText(): String {
            if (logLines.isEmpty()) {
                return "等待启动本地 Resin 核心引擎 (libresin_core.so)..."
            }
            return logLines.joinToString("\n")
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action ?: ACTION_START
        if (action == ACTION_STOP) {
            stopCoreEngine()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }

        val prefs = getSharedPreferences("resin_prefs", Context.MODE_PRIVATE)
        val port = prefs.getString("port", "2260") ?: "2260"
        val adminToken = prefs.getString("admin_token", "admin123") ?: "admin123"
        val proxyToken = prefs.getString("proxy_token", "my-token") ?: "my-token"

        startForeground(NOTIFICATION_ID, buildNotification("本地 Resin 代理池网关运行中 (端口 $port)"))
        startCoreEngine(port, adminToken, proxyToken)
        return START_STICKY
    }

    private fun startCoreEngine(port: String, adminToken: String, proxyToken: String) {
        if (isRunning()) {
            appendLog("Resin 核心引擎已在运行中 (端口: $port)")
            return
        }

        Thread {
            try {
                val nativeDir = File(applicationInfo.nativeLibraryDir)
                val coreBin = File(nativeDir, "libresin_core.so")
                if (!coreBin.exists()) {
                    appendLog("未在 ${nativeDir.absolutePath} 找到 libresin_core.so，请使用远程控制模式连接网关。")
                    return@Thread
                }
                coreBin.setExecutable(true)

                val baseDir = File(filesDir, "resin")
                val stateDir = File(baseDir, "state").apply { mkdirs() }
                val cacheDir = File(baseDir, "cache").apply { mkdirs() }
                val logDir = File(baseDir, "log").apply { mkdirs() }

                val pb = ProcessBuilder(coreBin.absolutePath)
                pb.directory(baseDir)
                pb.redirectErrorStream(true)

                val env = pb.environment()
                env["RESIN_ADMIN_TOKEN"] = adminToken
                env["RESIN_PROXY_TOKEN"] = proxyToken
                env["RESIN_LISTEN_ADDRESS"] = "0.0.0.0"
                env["RESIN_PORT"] = port
                env["RESIN_STATE_DIR"] = stateDir.absolutePath
                env["RESIN_CACHE_DIR"] = cacheDir.absolutePath
                env["RESIN_LOG_DIR"] = logDir.absolutePath
                env["RESIN_PROBE_CONCURRENCY"] = "250"
                env["RESIN_BOOTSTRAP_DNS"] = "223.5.5.5:53,119.29.29.29:53,8.8.8.8:53,1.1.1.1:53"
                env["RESIN_NODE_DNS_UPSTREAMS"] = "[\"tls://223.5.5.5?sni=dns.alidns.com\",\"https://1.1.1.1/dns-query\"]"
                env["SSL_CERT_DIR"] = "/system/etc/security/cacerts:/apex/com.android.conscrypt/cacerts"

                appendLog("正在启动内置 Resin Go 核心网关引擎 (端口: $port)...")
                val proc = pb.start()
                coreProcess = proc

                val reader = BufferedReader(InputStreamReader(proc.inputStream, Charsets.UTF_8))
                var line: String?
                while (reader.readLine().also { line = it } != null) {
                    line?.let { appendLog(it) }
                }
                val code = proc.waitFor()
                appendLog("Resin 核心引擎已退出 (ExitCode=$code)")
            } catch (e: Exception) {
                appendLog("启动 Resin 核心引擎异常: ${e.message}")
            }
        }.start()
    }

    private fun stopCoreEngine() {
        try {
            coreProcess?.let {
                appendLog("正在停止本地 Resin 核心引擎...")
                it.destroy()
            }
            coreProcess = null
        } catch (e: Exception) {
            appendLog("停止引擎异常: ${e.message}")
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Resin 本地代理池网关服务",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "保持 Resin 高性能粘性代理池网关在后台稳定运行"
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(content: String): Notification {
        val openIntent = Intent(this, MainActivity::class.java)
        val pendingOpen = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val stopIntent = Intent(this, ResinCoreService::class.java).apply {
            action = ACTION_STOP
        }
        val pendingStop = PendingIntent.getService(
            this, 1, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Resin 智能代理池网关")
            .setContentText(content)
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentIntent(pendingOpen)
            .setOngoing(true)
            .addAction(android.R.drawable.ic_media_pause, "停止网关", pendingStop)
            .build()
    }

    override fun onDestroy() {
        stopCoreEngine()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
