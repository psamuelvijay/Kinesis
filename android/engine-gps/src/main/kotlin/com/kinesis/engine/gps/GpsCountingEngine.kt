package com.kinesis.engine.gps

import com.kinesis.core.model.CountingEngine
import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.EngineListener
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RuntimeRequirement

/**
 * App A engine. Counts from GPS fixes only (Phase 2 GPS-only Random Forest on 5 s windows);
 * it never touches a motion or step sensor.
 *
 * Each start is a new epoch (its cumulative values begin at 0), so the runtime's reducer carries
 * the earlier session value over without a jump.
 *
 * Each closed window is counted at most once, keyed by its index on the location clock
 * (elapsedRealtime / 5 s). [lastCountedWindow] survives service restarts in this process and, through
 * [restoreCountedWindow] and [EngineListener.onWindowCounted], process death. elapsedRealtime restarts at
 * boot, so a first fix whose window index is below the cursor means a reboot and the cursor is cleared.
 */
class GpsCountingEngine(
    private val source: GpsFixSource,
    private val estimatorFactory: () -> WindowEstimator,
    private val epochProvider: () -> Long = System::currentTimeMillis,
) : CountingEngine {

    override val profile: MethodProfile = MethodProfile.GPS_ONLY

    override val requirements: Set<RuntimeRequirement> = setOf(
        RuntimeRequirement.FINE_LOCATION,
        RuntimeRequirement.LOCATION_SERVICES,
        RuntimeRequirement.NOTIFICATIONS_OPTIONAL,
    )

    private var active = false
    private var lastCountedWindow: Long? = null

    override fun availability(): EngineAvailability = source.availability()

    @Synchronized
    override fun restoreCountedWindow(index: Long?) {
        if (lastCountedWindow == null) lastCountedWindow = index
    }

    @Synchronized
    override fun start(listener: EngineListener) {
        if (active) return
        active = true
        val estimator = estimatorFactory()
        val epoch = epochProvider()
        var steps = 0.0
        var distance = 0.0
        var firstFix = true
        listener.onSteps(epoch, 0.0)
        listener.onDistance(epoch, 0.0)
        source.start(
            onFix = { fix ->
                synchronized(this) {
                    if (firstFix) {
                        firstFix = false
                        val cursor = lastCountedWindow
                        if (cursor != null && windowIndexOf(fix.elapsedRealtimeNanos / 1e6) < cursor) {
                            lastCountedWindow = null // clock restarted: reboot
                        }
                    }
                    for (w in estimator.onFix(fix)) {
                        distance += w.distanceM
                        val cursor = lastCountedWindow
                        if (w.status == WindowStatus.PREDICTED) {
                            listener.onGpsDataStatus(false)
                            if (cursor == null || w.index > cursor) {
                                steps += w.steps
                                lastCountedWindow = w.index
                                listener.onWindowCounted(w.index)
                            }
                        } else {
                            listener.onGpsDataStatus(true)
                        }
                    }
                    listener.onSteps(epoch, steps)
                    listener.onDistance(epoch, distance)
                    listener.onFix(fix.speedMps?.toFloat(), fix.accuracyM?.toFloat())
                }
            },
            onProblem = listener::onUnavailable,
        )
    }

    @Synchronized
    override fun stop() {
        if (!active) return
        active = false
        source.stop()
    }

    /** Nothing to do: Reset only moves the runtime's baseline, never the GPS estimate. */
    override fun onReset() = Unit
}
