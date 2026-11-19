package com.kinesis.ui.shared

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RunStatus
import com.kinesis.ui.shared.preview.FakeCountingController
import com.kinesis.ui.shared.preview.FakeStates
import com.kinesis.ui.shared.preview.NoOpPermissionBridge
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class ParityTest {
    @get:Rule
    val rule = createComposeRule()

    private fun string(id: Int) = InstrumentationRegistry.getInstrumentation().targetContext.getString(id)

    private fun ComposeContentTestRule.show(profile: MethodProfile) {
        val state = FakeStates.state(profile, RunStatus.Counting, 1234L)
        setContent { KinesisApp(FakeCountingController(profile, state), NoOpPermissionBridge) }
    }

    private fun ComposeContentTestRule.tags(): List<String> =
        onAllNodes(SemanticsMatcher.keyIsDefined(SemanticsProperties.TestTag), useUnmergedTree = true)
            .fetchSemanticsNodes()
            .map { it.config[SemanticsProperties.TestTag] }

    private fun tagsFor(profile: MethodProfile): List<String> {
        rule.show(profile)
        rule.waitForIdle()
        return rule.tags()
    }

    @Test
    fun gpsOnlyTagOrderIsRecorded() {
        val tags = tagsFor(MethodProfile.GPS_ONLY)
        assertTrue(tags.containsAll(listOf(UiTags.STEPS_HERO, UiTags.ACTION_TOGGLE, UiTags.ACTION_RESET)))
        assertEquals(EXPECTED_ORDER, tags)
    }

    @Test
    fun sensorFusionTagOrderMatchesGpsOnly() {
        assertEquals(EXPECTED_ORDER, tagsFor(MethodProfile.SENSOR_FUSION))
    }

    @Test
    fun gpsOnlyShowsNotUsedForSensorFields() {
        rule.show(MethodProfile.GPS_ONLY)
        val text = string(R.string.field_not_used)
        listOf(UiTags.FIELD_SENSOR_TOTAL, UiTags.FIELD_ACTIVITY, UiTags.FIELD_MOVEMENT_VERDICT).forEach {
            rule.onNodeWithTag(it).assertTextContains(text, substring = true)
        }
    }

    @Test
    fun sensorFusionShowsNotEnabledForGpsFields() {
        rule.show(MethodProfile.SENSOR_FUSION)
        val text = string(R.string.field_not_enabled)
        listOf(UiTags.FIELD_GPS_SPEED, UiTags.FIELD_GPS_ACCURACY, UiTags.FIELD_SESSION_DISTANCE).forEach {
            rule.onNodeWithTag(it).assertTextContains(text, substring = true)
        }
    }

    @Test
    fun actionsAreAtLeast48dpInBothProfiles() {
        MethodProfile.GPS_ONLY.let { rule.show(it) }
        rule.onNodeWithTag(UiTags.ACTION_TOGGLE).assertHeightIsAtLeast(48.dp)
        rule.onNodeWithTag(UiTags.ACTION_RESET).assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun actionsAreAtLeast48dpInFusionProfile() {
        rule.show(MethodProfile.SENSOR_FUSION)
        rule.onNodeWithTag(UiTags.ACTION_TOGGLE).assertHeightIsAtLeast(48.dp)
        rule.onNodeWithTag(UiTags.ACTION_RESET).assertHeightIsAtLeast(48.dp)
    }

    private companion object {
        /** The Home layout contract: identical for both profiles. */
        val EXPECTED_ORDER = listOf(
            UiTags.BANNER,
            UiTags.STATUS,
            UiTags.STEPS_HERO,
            UiTags.STEPS_VALUE,
            UiTags.FIELD_SESSION_DISTANCE,
            UiTags.FIELD_GPS_SPEED,
            UiTags.FIELD_GPS_ACCURACY,
            UiTags.FIELD_SENSOR_TOTAL,
            UiTags.FIELD_ACTIVITY,
            UiTags.FIELD_MOVEMENT_VERDICT,
            UiTags.ACTION_TOGGLE,
            UiTags.ACTION_RESET,
            UiTags.BATTERY_HINT,
            UiTags.BATTERY_OPEN,
            UiTags.BATTERY_DISMISS,
            UiTags.TAB_HOME,
            UiTags.TAB_SETTINGS,
            UiTags.TAB_ABOUT,
        )
    }
}
