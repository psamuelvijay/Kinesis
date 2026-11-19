package com.kinesis.ui.shared

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollTo
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.UnavailableReason
import com.kinesis.ui.shared.preview.FakeCountingController
import com.kinesis.ui.shared.preview.FakeStates
import com.kinesis.ui.shared.preview.NoOpPermissionBridge
import org.junit.Rule
import org.junit.Test

/** Denied-permission path: the card is shown in both apps and Start is disabled. */
class PermissionCardTest {
    @get:Rule
    val rule = createComposeRule()

    private fun showDenied(profile: MethodProfile) {
        val state = FakeStates.state(
            profile,
            RunStatus.Blocked(UnavailableReason.PERMISSION_DENIED),
            0L,
            permissionsGranted = false,
        )
        rule.setContent { KinesisApp(FakeCountingController(profile, state), NoOpPermissionBridge) }
    }

    @Test
    fun gpsOnlyDeniedShowsPermissionCard() {
        showDenied(MethodProfile.GPS_ONLY)
        rule.onNodeWithTag(UiTags.PERMISSION_CARD).assertIsDisplayed()
        rule.onNodeWithTag(UiTags.ACTION_TOGGLE).performScrollTo().assertIsNotEnabled()
    }

    @Test
    fun sensorFusionDeniedShowsPermissionCard() {
        showDenied(MethodProfile.SENSOR_FUSION)
        rule.onNodeWithTag(UiTags.PERMISSION_CARD).assertIsDisplayed()
        rule.onNodeWithTag(UiTags.ACTION_TOGGLE).performScrollTo().assertIsNotEnabled()
    }
}