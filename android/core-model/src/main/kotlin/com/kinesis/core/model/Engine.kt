package com.kinesis.core.model

import kotlinx.coroutines.flow.StateFlow

enum class RuntimeRequirement {
    FINE_LOCATION,
    ACTIVITY_RECOGNITION,
    LOCATION_SERVICES,
    NOTIFICATIONS_OPTIONAL,
}

sealed interface EngineAvailability {
    data object Available : EngineAvailability
    data class Unavailable(val reason: UnavailableReason) : EngineAvailability
}

/** Receives raw engine output. Cumulative values are per [epoch] and never reset by callers. */
interface EngineListener {
    fun onSteps(epoch: Long, cumulative: Double)
    fun onDistance(epoch: Long, cumulativeM: Double)
    fun onFix(speedMps: Float?, accuracyM: Float?)
    fun onUnavailable(reason: UnavailableReason)
}

/**
 * One step/distance source. App A supplies a GPS-only engine, App B a physical
 * step-counter engine. The foreground service type is an Android concern and is
 * deliberately not part of this interface.
 */
interface CountingEngine {
    val profile: MethodProfile
    val requirements: Set<RuntimeRequirement>
    fun availability(): EngineAvailability
    fun start(listener: EngineListener)
    fun stop()
    /** Called after a session reset; the engine must not reset its source. */
    fun onReset()
}

/** What the UI talks to. */
interface CountingController {
    /** Static description of the method; the UI uses it for the banner and field policies. */
    val profile: MethodProfile
    val state: StateFlow<CountingUiState>
    fun start()
    fun stop()
    fun resetSteps()
    fun refreshAvailability()
}