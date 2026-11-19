package com.kinesis.gpsonly

import android.app.Application
import com.kinesis.core.model.CountingController
import com.kinesis.core.model.MethodProfile
import com.kinesis.ui.shared.preview.FakeCountingController

/** Wiring only. FEAT-003 replaces the fake controller with the real counting runtime. */
class GpsOnlyContainer {
    val controller: CountingController = FakeCountingController(MethodProfile.GPS_ONLY)
}

class GpsOnlyApplication : Application() {
    val container by lazy { GpsOnlyContainer() }
}