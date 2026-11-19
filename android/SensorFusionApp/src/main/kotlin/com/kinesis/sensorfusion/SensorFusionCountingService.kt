package com.kinesis.sensorfusion

import android.content.pm.ServiceInfo
import android.os.Build
import com.kinesis.core.runtime.CountingService

class SensorFusionCountingService : CountingService() {
    override val startForegroundType: Int =
        if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH else 0
}