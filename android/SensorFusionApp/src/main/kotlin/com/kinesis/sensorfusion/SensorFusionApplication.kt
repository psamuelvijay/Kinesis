package com.kinesis.sensorfusion

import android.app.Application
import android.content.Context
import android.hardware.SensorManager
import android.os.SystemClock
import com.kinesis.core.runtime.AndroidCountingController
import com.kinesis.core.runtime.CountingRuntime
import com.kinesis.core.runtime.CountingStore
import com.kinesis.core.runtime.RuntimeProvider
import com.kinesis.core.runtime.androidRequirementEvaluator
import com.kinesis.engine.physical.BootEpochProvider
import com.kinesis.engine.physical.PhysicalStepsCountingEngine
import com.kinesis.engine.physical.SensorStepCounterFeed
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import java.io.File

/** Process singletons for App B: physical step engine, persisted store, runtime and controller. */
class SensorFusionContainer(app: Application) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val store = CountingStore.create(
        File(app.filesDir, "datastore/" + CountingStore.FILE_NAME),
        scope,
    )
    private val engine = PhysicalStepsCountingEngine(
        feed = SensorStepCounterFeed(app.getSystemService(Context.SENSOR_SERVICE) as SensorManager),
        epochProvider = BootEpochProvider(app.contentResolver)::epoch,
    )
    val runtime = CountingRuntime(
        engine = engine,
        store = store,
        scope = scope,
        elapsedRealtimeMs = SystemClock::elapsedRealtime,
        evaluator = androidRequirementEvaluator(app, engine.requirements),
    )
    val controller = AndroidCountingController(app, runtime, SensorFusionCountingService::class.java)
}

class SensorFusionApplication : Application(), RuntimeProvider {
    val container by lazy { SensorFusionContainer(this) }
    override val runtime: CountingRuntime get() = container.runtime
}