package com.kinesis.engine.physical

import com.kinesis.core.model.CountingEngine
import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.EngineListener
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.core.model.UnavailableReason

/**
 * App B engine for M1: forwards the hardware step counter to the runtime. No location, no IMU,
 * no fallback to TYPE_STEP_DETECTOR or the accelerometer.
 */
class PhysicalStepsCountingEngine(
    private val feed: StepCounterFeed,
    private val epochProvider: () -> Long,
) : CountingEngine {

    override val profile: MethodProfile = MethodProfile.SENSOR_FUSION

    override val requirements: Set<RuntimeRequirement> = setOf(
        RuntimeRequirement.ACTIVITY_RECOGNITION,
        RuntimeRequirement.NOTIFICATIONS_OPTIONAL,
    )

    private var active = false

    override fun availability(): EngineAvailability =
        if (feed.isAvailable) EngineAvailability.Available else EngineAvailability.Unavailable(UnavailableReason.SENSOR_MISSING)

    @Synchronized
    override fun start(listener: EngineListener) {
        if (active) return
        if (!feed.isAvailable) {
            listener.onUnavailable(UnavailableReason.SENSOR_MISSING)
            return
        }
        active = true
        val epoch = epochProvider()
        // Registering again delivers the current total, which the reducer treats as a no-op.
        feed.start { cumulative -> listener.onSteps(epoch, cumulative.toDouble()) }
    }

    @Synchronized
    override fun stop() {
        if (!active) return
        active = false
        feed.stop()
    }

    /** Nothing to do: Reset only moves the runtime's baseline, never the hardware counter. */
    override fun onReset() = Unit
}
