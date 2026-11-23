package com.resinat.resin.android

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.ProxyInfo
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor

class ResinVpnService : VpnService() {

    companion object {
        const val ACTION_VPN_START = "com.resinat.resin.android.ACTION_VPN_START"
        const val ACTION_VPN_STOP = "com.resinat.resin.android.ACTION_VPN_STOP"

        @Volatile
        var vpnInterface: ParcelFileDescriptor? = null

        fun isVpnActive(): Boolean = vpnInterface != null
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action ?: ACTION_VPN_START
        if (action == ACTION_VPN_STOP) {
            stopVpnTunnel()
            stopSelf()
            return START_NOT_STICKY
        }

        startVpnTunnel()
        return START_STICKY
    }

    private fun startVpnTunnel() {
        if (vpnInterface != null) {
            ResinCoreService.appendLog("VPN 透明代理隧道已在运行中")
            return
        }

        try {
            val prefs = getSharedPreferences("resin_prefs", Context.MODE_PRIVATE)
            val portStr = prefs.getString("port", "2260") ?: "2260"
            val port = portStr.toIntOrNull() ?: 2260
            val mode = prefs.getInt("vpn_app_mode", 0) // 0=全局(排除自身), 1=仅指定应用(白名单), 2=排除指定应用(黑名单)
            val pkgRaw = prefs.getString("vpn_app_packages", "") ?: ""
            val pkgList = pkgRaw.split(",", ";", "\n", " ").map { it.trim() }.filter { it.isNotEmpty() }

            val openIntent = Intent(this, MainActivity::class.java)
            val pendingOpen = PendingIntent.getActivity(
                this, 0, openIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val builder = Builder()
                .setSession("Resin 粘性代理池透明隧道")
                .setMtu(1500)
                .addAddress("10.226.0.1", 30)
                .addDnsServer("223.5.5.5")
                .addDnsServer("8.8.8.8")
                .setConfigureIntent(pendingOpen)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                builder.setHttpProxy(ProxyInfo.buildDirectProxy("127.0.0.1", port))
            }

            // 分应用 (Per-App) 流量控制与自身防回环
            when (mode) {
                1 -> {
                    var added = 0
                    for (pkg in pkgList) {
                        if (pkg == packageName) continue
                        try {
                            builder.addAllowedApplication(pkg)
                            added++
                        } catch (_: Exception) {}
                    }
                    if (added == 0) {
                        try { builder.addDisallowedApplication(packageName) } catch (_: Exception) {}
                    }
                }
                2 -> {
                    try { builder.addDisallowedApplication(packageName) } catch (_: Exception) {}
                    for (pkg in pkgList) {
                        try { builder.addDisallowedApplication(pkg) } catch (_: Exception) {}
                    }
                }
                else -> {
                    try { builder.addDisallowedApplication(packageName) } catch (_: Exception) {}
                }
            }

            vpnInterface = builder.establish()
            if (vpnInterface != null) {
                val modeDesc = when (mode) {
                    1 -> "白名单分应用模式 (${pkgList.size} 个应用)"
                    2 -> "黑名单排除模式 (${pkgList.size} 个应用)"
                    else -> "全局透明代理模式 (已自动排除自身防回环)"
                }
                ResinCoreService.appendLog("已建立 Android VPN 透明代理隧道 -> 127.0.0.1:$port [$modeDesc]")
            } else {
                ResinCoreService.appendLog("VPN 隧道未能建立 (用户未授权或被系统占用)")
            }
        } catch (e: Exception) {
            ResinCoreService.appendLog("启动 VPN 透明代理异常: ${e.message}")
        }
    }

    private fun stopVpnTunnel() {
        try {
            vpnInterface?.close()
            vpnInterface = null
            ResinCoreService.appendLog("已关闭 Android VPN 透明代理隧道")
        } catch (e: Exception) {
            ResinCoreService.appendLog("关闭 VPN 隧道异常: ${e.message}")
        }
    }

    override fun onDestroy() {
        stopVpnTunnel()
        super.onDestroy()
    }
}
