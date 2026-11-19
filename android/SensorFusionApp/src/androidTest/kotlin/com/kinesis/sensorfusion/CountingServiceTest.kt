package com.kinesis.sensorfusion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorManager
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.UnavailableReason
import com.kinesis.ui.shared.UiTags
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test

class CountingServiceTest {

    @get:Rule
    val rule = createAndroidComposeRule<MainActivity>()

    private val context: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val container get() = (context.applicationContext as SensorFusionApplication).container

    private fun hasStepCounter(): Boolean {
        val sm = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        return sm.getDefaultSensor(Sensor.TYPE_STEP_COUNTER) != null
    }

    @Test
    fun manifestRequestsNoInternetAndNoLocation() {
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
        val requested = info.requestedPermissions.orEmpty().toSet()
        assertFalse(Manifest.permission.INTERNET in requested)
        assertFalse(Manifest.permission.ACCESS_FINE_LOCATION in requested)
        assertFalse(Manifest.permission.ACCESS_COARSE_LOCATION in requested)
    }

    /** The emulator normally has no TYPE_STEP_COUNTER; then Start must be disabled with a reason. */
    @Test
    fun missingStepCounterDisablesStartWithExplanation() {
        assumeTrue("device has a step counter", !hasStepCounter())
        InstrumentationRegistry.getInstrumentation().uiAutomation
            .grantRuntimePermission(context.packageName, Manifest.permission.ACTIVITY_RECOGNITION)
        rule.runOnUiThread { container.controller.refreshAvailability() }
        rule.waitUntil(5_000) {
            container.runtime.state.value.runStatus == RunStatus.Blocked(UnavailableReason.SENSOR_MISSING)
        }
        // Shown in the status card and in the sensor-total field.
        rule.onAllNodesWithText("Step counter not available on this device", substring = true).onFirst().assertExists()
        rule.onNodeWithTag(UiTags.ACTION_TOGGLE).performScrollTo().assertIsNotEnabled()
        rule.runOnUiThread { container.controller.start() }
        assertEquals(RunStatus.Blocked(UnavailableReason.SENSOR_MISSING), container.runtime.state.value.runStatus)
    }

    @Test
    fun resetButtonZeroesDisplayedSteps() {
        rule.onNodeWithTag(UiTags.ACTION_RESET).performScrollTo().performClick()
        rule.waitUntil(5_000) { container.runtime.state.value.sessionSteps == 0L }
        rule.onNodeWithTag(UiTags.STEPS_VALUE).performScrollTo().assertTextEquals("0")
    }
}