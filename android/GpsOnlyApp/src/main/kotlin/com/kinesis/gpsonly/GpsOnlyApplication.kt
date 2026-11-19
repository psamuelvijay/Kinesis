package com.kinesis.gpsonly

import android.app.Application
import com.kinesis.core.runtime.AndroidCountingController
import com.kinesis.core.runtime.CountingRuntime
import com.kinesis.core.runtime.CountingStore
import com.kinesis.core.runtime.RuntimeProvider
import com.kinesis.core.runtime.androidRequirementEvaluator
import com.kinesis.engine.gps.GpsCountingEngine
import com.kinesis.engine.gps.GpsWindowPipeline
import com.kinesis.engine.gps.PlatformLocationSource
import com.kinesis.engine.gps.RandomForestModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import android.os.SystemClock
import java.io.File

/** Process singletons for App A: GPS engine, persisted store, runtime and controller. */
class GpsOnlyContainer(app: Application) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val store = CountingStore.create(
        File(app.filesDir, "datastore/" + CountingStore.FILE_NAME),
        scope,
    )
    private val model by lazy {
        app.assets.open("gps_rf_model.bin").use { RandomForestModel.load(it) }
    }
    private val engine = GpsCountingEngine(PlatformLocationSource(app), estimatorFactory = { GpsWindowPipeline.clockAligned(model) })
    val runtime = CountingRuntime(
        engine = engine,
        store = store,
        scope = scope,
        elapsedRealtimeMs = SystemClock::elapsedRealtime,
        evaluator = androidRequirementEvaluator(app, engine.requirements),
    )
    val controller = AndroidCountingController(app, runtime, GpsCountingService::class.java)
}

class GpsOnlyApplication : Application(), RuntimeProvider {
    val container by lazy { GpsOnlyContainer(this) }
    override val runtime: CountingRuntime get() = container.runtime
}