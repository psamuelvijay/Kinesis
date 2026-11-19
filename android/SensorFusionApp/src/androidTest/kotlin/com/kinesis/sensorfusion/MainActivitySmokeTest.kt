package com.kinesis.sensorfusion

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import com.kinesis.ui.shared.UiTags
import org.junit.Rule
import org.junit.Test

class MainActivitySmokeTest {
    @get:Rule
    val rule = createAndroidComposeRule<MainActivity>()

    @Test
    fun launchShowsStepsHero() {
        rule.onNodeWithTag(UiTags.STEPS_HERO).assertIsDisplayed()
    }
}