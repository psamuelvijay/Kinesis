package com.kinesis.gpsonly

import android.Manifest
import android.app.ActivityManager
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.kinesis.core.model.RunStatus
import com.kinesis.core.runtime.CountingService
import com.kinesis.ui.shared.UiTags
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class CountingServiceTest {

    @get:Rule
    val rule = createAndroidComposeRule<MainActivity>()

    private val context: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val container get() = (context.applicationContext as GpsOnlyApplication).container

    private fun grant() {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.grantRuntimePermission(context.packageName, Manifest.permission.ACCESS_FINE_LOCATION)
        automation.grantRuntimePermission(context.packageName, Manifest.permission.ACCESS_COARSE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) {
            automation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        rule.runOnUiThread { container.controller.refreshAvailability() }
    }

    @Suppress("DEPRECATION") // getRunningServices still reports the caller's own services
    private fun ownServiceCount(): Int {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        return am.getRunningServices(Int.MAX_VALUE).count {
            it.service.packageName == context.packageName && it.service.className == GpsCountingService::class.java.name
        }
    }

    private fun waitForCounting() {
        rule.waitUntil(10_000) { container.runtime.state.value.runStatus == RunStatus.Counting }
    }

    @After
    fun tearDown() {
        rule.runOnUiThread { container.controller.stop() }
    }

    @Test
    fun manifestRequestsNoActivityRecognitionAndNoInternet() {
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
        val requested = info.requestedPermissions.orEmpty().toSet()
        assertFalse(Manifest.permission.ACTIVITY_RECOGNITION in requested)
        assertFalse(Manifest.permission.INTERNET in requested)
        assertFalse("android.permission.FOREGROUND_SERVICE_HEALTH" in requested)
        assertTrue(Manifest.permission.ACCESS_FINE_LOCATION in requested)
    }

    @Test
    fun startShowsOngoingNotificationAndRecreationKeepsOneService() {
        grant()
        rule.onNodeWithTag(UiTags.ACTION_TOGGLE).performScrollTo().performClick()
        waitForCounting()
        val nm = context.getSystemService(NotificationManager::class.java)
        rule.waitUntil(15_000) { nm.activeNotifications.any { it.id == CountingService.NOTIFICATION_ID } }
        assertEquals(1, ownServiceCount())
        val before = container.runtime.state.value.sessionSteps

        rule.activityRule.scenario.recreate()
        rule.waitForIdle()
        // A second Start from the recreated Activity must not create a second registration.
        rule.runOnUiThread { container.controller.start() }
        waitForCounting()
        assertEquals(1, ownServiceCount())
        assertEquals(before, container.runtime.state.value.sessionSteps)
    }

    @Test
    fun resetButtonZeroesDisplayedSteps() {
        grant()
        rule.onNodeWithTag(UiTags.ACTION_RESET).performScrollTo().performClick()
        rule.waitUntil(5_000) { container.runtime.state.value.sessionSteps == 0L }
        rule.onNodeWithTag(UiTags.STEPS_VALUE).performScrollTo().assertTextEquals("0")
    }
}