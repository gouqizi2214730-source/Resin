package com.resinat.resin.android

import android.app.Activity
import android.content.Context
import android.content.res.Configuration
import android.graphics.Rect
import android.os.Build
import android.view.View
import android.view.WindowManager
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import kotlin.math.max
import kotlin.math.min

/**
 * 异形屏（居中/左上/右上挖孔屏、药丸双挖孔、刘海屏、水滴屏、双曲面瀑布屏、折叠屏）
 * 与屏下摄像头（UDC - Under-Display Camera）全场景自适应布局与光学防眩光引擎。
 */
class AdaptiveScreenManager(private val activity: Activity) {

    companion object {
        const val MODE_AUTO = 0          // 智能自动感应 (自动区分物理挖孔/刘海与真全面屏/屏下摄像头)
        const val MODE_UDC_OPTICAL = 1   // 屏下摄像头 (UDC) 光学防眩光与感光轴避让模式
        const val MODE_CUTOUT_SAFE = 2   // 异形屏 (挖孔/药丸/刘海) 增强四向安全避让模式
        const val MODE_CURVED_FOLD = 3   // 曲面瀑布屏 / 折叠屏大屏防误触自适应模式
    }

    data class ScreenAdaptationProfile(
        val mode: Int,
        val screenWidthPx: Int,
        val screenHeightPx: Int,
        val density: Float,
        val aspectRatio: Float,
        val isLandscape: Boolean,
        val isFoldableOrTablet: Boolean,
        val cameraCutoutType: String,
        val cutoutRects: List<Rect>,
        val safeTopPx: Int,
        val safeBottomPx: Int,
        val safeLeftPx: Int,
        val safeRightPx: Int,
        val headerLeftShiftPx: Int,
        val headerRightShiftPx: Int,
        val showUdcOpticalGuard: Boolean,
        val udcZoneWidthPx: Int,
        val udcZoneHeightPx: Int
    )

    var currentProfile: ScreenAdaptationProfile? = null
        private set

    fun configureWindowEdgeToEdge() {
        val window = activity.window
        WindowCompat.setDecorFitsSystemWindows(window, false)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            val lp = window.attributes
            lp.layoutInDisplayCutoutMode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            } else {
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
            window.attributes = lp
        }

        val controller = WindowInsetsControllerCompat(window, window.decorView)
        controller.isAppearanceLightStatusBars = false
        controller.isAppearanceLightNavigationBars = false
    }

    fun attachAdaptiveInsetsListener(
        rootView: View,
        onProfileUpdated: (ScreenAdaptationProfile) -> Unit
    ) {
        ViewCompat.setOnApplyWindowInsetsListener(rootView) { _, insets ->
            val profile = computeProfile(insets)
            currentProfile = profile
            onProfileUpdated(profile)
            insets
        }
        ViewCompat.requestApplyInsets(rootView)
    }

    fun recomputeNow(rootView: View, onProfileUpdated: (ScreenAdaptationProfile) -> Unit) {
        val insets = ViewCompat.getRootWindowInsets(rootView)
        val profile = computeProfile(insets)
        currentProfile = profile
        onProfileUpdated(profile)
    }

    private fun computeProfile(insets: WindowInsetsCompat?): ScreenAdaptationProfile {
        val prefs = activity.getSharedPreferences("resin_prefs", Context.MODE_PRIVATE)
        val mode = prefs.getInt("screen_adapt_mode", MODE_AUTO)
        val extraTopDp = prefs.getInt("screen_extra_top_dp", 0)
        val curvedEdgeDp = prefs.getInt("screen_curved_edge_dp", 0)

        val dm = activity.resources.displayMetrics
        val density = dm.density
        val wPx = dm.widthPixels
        val hPx = dm.heightPixels
        val longSide = max(wPx, hPx).toFloat()
        val shortSide = max(1, min(wPx, hPx)).toFloat()
        val aspectRatio = longSide / shortSide
        val isLandscape = activity.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
        val smallestWidthDp = shortSide / density
        val isFoldableOrTablet = smallestWidthDp >= 580f || (aspectRatio < 1.35f && wPx >= dp(600))

        val sysBars = insets?.getInsets(WindowInsetsCompat.Type.systemBars())
        val cutoutInsets = insets?.getInsets(WindowInsetsCompat.Type.displayCutout())
        val imeInsets = insets?.getInsets(WindowInsetsCompat.Type.ime())
        val displayCutout = insets?.displayCutout

        val boundingRects = mutableListOf<Rect>()
        if (displayCutout != null) {
            boundingRects.addAll(displayCutout.boundingRects)
        }

        // 识别摄像头开孔位置类型（居中挖孔/水滴、左上挖孔、右上挖孔、药丸宽刘海、或无开孔屏下摄像头 UDC）
        var cameraType = "真全面屏 / 屏下摄像头 (UDC 无物理盲孔)"
        var leftShiftPx = 0
        var rightShiftPx = 0

        if (boundingRects.isNotEmpty()) {
            val topRect = boundingRects.minByOrNull { it.top } ?: boundingRects[0]
            val rectWidthDp = topRect.width() / density
            val centerX = topRect.centerX()
            cameraType = when {
                topRect.top > hPx / 3 && isLandscape -> {
                    "横屏侧边摄像头开孔 (${topRect.width()}x${topRect.height()}px)"
                }
                centerX < wPx * 0.35 -> {
                    leftShiftPx = max(0, topRect.right - dp(8))
                    "左上角前置挖孔屏 (${topRect.width()}x${topRect.height()}px)"
                }
                centerX > wPx * 0.65 -> {
                    rightShiftPx = max(0, wPx - topRect.left - dp(8))
                    "右上角前置挖孔屏 (${topRect.width()}x${topRect.height()}px)"
                }
                rectWidthDp >= 72f -> {
                    "居中宽药丸双挖孔 / 刘海异形屏 (${topRect.width()}x${topRect.height()}px)"
                }
                else -> {
                    "顶部居中单挖孔 / 水滴异形屏 (${topRect.width()}x${topRect.height()}px)"
                }
            }
        } else if (isFoldableOrTablet) {
            cameraType = "折叠屏展开态 / 大屏全视屏 (含屏下摄像头 UDC 兼容)"
        }

        val rawTop = max(sysBars?.top ?: dp(28), cutoutInsets?.top ?: 0)
        val rawBottom = max(
            max(sysBars?.bottom ?: dp(16), cutoutInsets?.bottom ?: 0),
            imeInsets?.bottom ?: 0
        )
        val rawLeft = max(sysBars?.left ?: 0, cutoutInsets?.left ?: 0)
        val rawRight = max(sysBars?.right ?: 0, cutoutInsets?.right ?: 0)

        // 是否启用屏下摄像头 (UDC) 低亮度光学防眩光保护带
        val isAutoUdcCandidate = boundingRects.isEmpty() && aspectRatio >= 1.95f && !isLandscape
        val showUdcOpticalGuard = (mode == MODE_UDC_OPTICAL) || (mode == MODE_AUTO && isAutoUdcCandidate)

        val modeExtraTopPx = when (mode) {
            MODE_UDC_OPTICAL -> dp(10)
            MODE_CUTOUT_SAFE -> dp(8)
            else -> dp(4)
        }
        val modeExtraEdgePx = when (mode) {
            MODE_CURVED_FOLD -> max(dp(12), dp(curvedEdgeDp))
            else -> dp(curvedEdgeDp)
        }

        val safeTopPx = rawTop + modeExtraTopPx + dp(extraTopDp)
        val safeBottomPx = max(dp(10), rawBottom)
        val safeLeftPx = rawLeft + modeExtraEdgePx
        val safeRightPx = rawRight + modeExtraEdgePx

        // 当用户强制开启 Cutout Safe 模式以外部偏移保护顶栏文字时，仅在极端窄顶栏生效
        if (mode != MODE_CUTOUT_SAFE) {
            // 因为顶部已经整体下移 safeTopPx，已完全避开挖孔高度，无需水平压缩标题，除非在横屏模式
            if (!isLandscape) {
                leftShiftPx = 0
                rightShiftPx = 0
            }
        }

        return ScreenAdaptationProfile(
            mode = mode,
            screenWidthPx = wPx,
            screenHeightPx = hPx,
            density = density,
            aspectRatio = aspectRatio,
            isLandscape = isLandscape,
            isFoldableOrTablet = isFoldableOrTablet,
            cameraCutoutType = cameraType,
            cutoutRects = boundingRects,
            safeTopPx = safeTopPx,
            safeBottomPx = safeBottomPx,
            safeLeftPx = safeLeftPx,
            safeRightPx = safeRightPx,
            headerLeftShiftPx = leftShiftPx,
            headerRightShiftPx = rightShiftPx,
            showUdcOpticalGuard = showUdcOpticalGuard,
            udcZoneWidthPx = dp(136),
            udcZoneHeightPx = max(dp(26), rawTop)
        )
    }

    fun formatDiagnosticsText(): String {
        val p = currentProfile ?: return "正在采集屏幕与异形开孔传感器参数..."
        val modeName = when (p.mode) {
            MODE_UDC_OPTICAL -> "屏下摄像头 (UDC) 光学防眩光模式"
            MODE_CUTOUT_SAFE -> "异形屏/挖孔/刘海增强四向避让模式"
            MODE_CURVED_FOLD -> "双曲面瀑布屏/折叠屏防误触模式"
            else -> "智能自动感应模式 (Auto)"
        }
        val rectsStr = if (p.cutoutRects.isEmpty()) {
            "无物理盲孔 (0 个 Cutout 矩形，已启用屏下摄像头 UDC 光学兼容)"
        } else {
            p.cutoutRects.joinToString(", ") { "[${it.left},${it.top}-${it.right},${it.bottom}]" }
        }
        val orientStr = if (p.isLandscape) "横屏 (Landscape)" else "竖屏 (Portrait)"
        val foldStr = if (p.isFoldableOrTablet) "折叠屏大屏 / 平板布局" else "标准直板 / 曲面屏布局"

        return """
            • 当前自适应模式: $modeName
            • 屏幕形态识别: ${p.cameraCutoutType}
            • 物理分辨率与比例: ${p.screenWidthPx} × ${p.screenHeightPx} px (${String.format("%.2f", p.aspectRatio)}:1, $orientStr, $foldStr)
            • 异形开孔坐标 (Cutout Rects): $rectsStr
            • 四向安全避让内边距: 顶=${pxToDp(p.safeTopPx)}dp | 底=${pxToDp(p.safeBottomPx)}dp | 左=${pxToDp(p.safeLeftPx)}dp | 右=${pxToDp(p.safeRightPx)}dp
            • 屏下摄像头 (UDC) 消光保护带: ${if (p.showUdcOpticalGuard) "🟢 已激活 (#03050A 低亮光学防眩光区)" else "⚪ 按需待命"}
        """.trimIndent()
    }

    private fun dp(value: Int): Int = (value * activity.resources.displayMetrics.density).toInt()

    private fun pxToDp(px: Int): Int = (px / activity.resources.displayMetrics.density).toInt()
}
