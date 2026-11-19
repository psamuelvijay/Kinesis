package com.kinesis.sensorfusion

import android.app.Application
import com.kinesis.core.model.CountingController
import com.kinesis.core.model.MethodProfile
import com.kinesis.ui.shared.preview.FakeCountingController

/** Wiring only. FEAT-003 replaces the fake controller with the real counting runtime. */
class SensorFusionContainer {
    val controller: CountingController = FakeCountingController(MethodProfile.SENSOR_FUSION)
}

class SensorFusionApplication : Application() {
    val container by lazy { SensorFusionContainer() }
}