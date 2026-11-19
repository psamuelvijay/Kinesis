package com.kinesis.ui.shared.preview

import android.content.res.Configuration
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RunStatus
import com.kinesis.ui.shared.KinesisApp

@Preview(name = "Light", showBackground = true, heightDp = 900)
@Preview(name = "Dark", uiMode = Configuration.UI_MODE_NIGHT_YES, showBackground = true, heightDp = 900)
@Preview(name = "Font 1.3x", fontScale = 1.3f, showBackground = true, heightDp = 1100)
annotation class KinesisPreviews

@Composable
private fun PreviewApp(profile: MethodProfile) {
    val state = FakeStates.state(profile, RunStatus.Counting, 1234L)
    KinesisApp(FakeCountingController(profile, state), NoOpPermissionBridge)
}

@KinesisPreviews
@Composable
private fun GpsOnlyPreview() = PreviewApp(MethodProfile.GPS_ONLY)

@KinesisPreviews
@Composable
private fun SensorFusionPreview() = PreviewApp(MethodProfile.SENSOR_FUSION)
