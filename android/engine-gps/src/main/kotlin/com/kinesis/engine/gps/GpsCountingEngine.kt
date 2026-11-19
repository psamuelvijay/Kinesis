package com.kinesis.engine.gps

import com.kinesis.core.model.CountingEngine
import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.EngineListener
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RuntimeRequirement

/**
 * App A engine. Counts from GPS fixes only; it never touches a motion or step sensor.
 *
 * Each start is a new epoch (its cumulative values begin at 0), so the runtime's reducer carries
 * the earlier session value over without a jump.
 */
class GpsCountingEngine(
    private val source: GpsFixSource,
    private val estimatorFactory: () -> StepEstimator = { GpsStepEstimator() },
    private val epochProvider: () -> Long = System::currentTimeMillis,
) : CountingEngine {

    override val profile: MethodProfile = MethodProfile.GPS_ONLY

    override val requirements: Set<RuntimeRequirement> = setOf(
        RuntimeRequirement.FINE_LOCATION,
        RuntimeRequirement.LOCATION_SERVICES,
        RuntimeRequirement.NOTIFICATIONS_OPTIONAL,
    )

    private var active = false

    override fun availability(): EngineAvailability = source.availability()

    @Synchronized
    override fun start(listener: EngineListener) {
        if (active) return
        active = true
        val estimator = estimatorFactory()
        val epoch = epochProvider()
        listener.onSteps(epoch, 0.0)
        listener.onDistance(epoch, 0.0)
        source.start(
            onFix = { fix ->
                estimator.onFix(fix)
                listener.onSteps(epoch, estimator.cumulativeSteps)
                listener.onDistance(epoch, estimator.cumulativeDistanceM)
                listener.onFix(fix.speedMps, fix.accuracyM)
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
