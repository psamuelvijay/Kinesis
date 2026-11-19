package com.kinesis.gpsonly

import android.content.pm.ServiceInfo
import com.kinesis.core.runtime.CountingService

class GpsCountingService : CountingService() {
    override val startForegroundType: Int = ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
}