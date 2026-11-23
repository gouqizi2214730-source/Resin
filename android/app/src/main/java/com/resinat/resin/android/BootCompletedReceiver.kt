package com.resinat.resin.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

class BootCompletedReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        if (action == Intent.ACTION_BOOT_COMPLETED || action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            val prefs = context.getSharedPreferences("resin_prefs", Context.MODE_PRIVATE)
            val autoStart = prefs.getBoolean("boot_auto_start", true)
            if (autoStart) {
                ResinCoreService.appendLog("收到系统开机广播 ($action)，正在自动启动本地 Resin 核心引擎...")
                val svcIntent = Intent(context, ResinCoreService::class.java).apply {
                    this.action = ResinCoreService.ACTION_START
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(svcIntent)
                } else {
                    context.startService(svcIntent)
                }
            }
        }
    }
}
