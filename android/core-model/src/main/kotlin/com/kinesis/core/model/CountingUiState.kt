package com.kinesis.core.model

sealed interface RunStatus {
    data object Stopped : RunStatus
    data object Starting : RunStatus
    data object Counting : RunStatus
    /** Monitoring was requested but the engine or service is not delivering data. */
    data object Interrupted : RunStatus
    data class Blocked(val reason: UnavailableReason) : RunStatus
}

data class RequirementStatus(val requirement: RuntimeRequirement, val granted: Boolean)

data class CountingUiState(
    val runStatus: RunStatus = RunStatus.Stopped,
    /** floor(session) of the step channel. */
    val sessionSteps: Long = 0L,
    val stepsLabel: String,
    val gpsSpeedMps: FieldState<Float>,
    val gpsAccuracyM: FieldState<Float>,
    val sessionDistanceM: FieldState<Double>,
    val sensorTotalSinceBoot: FieldState<Long>,
    val activity: FieldState<String>,
    val movementVerdict: FieldState<String>,
    val requirements: List<RequirementStatus> = emptyList(),
    val canStart: Boolean = false,
    /** "GPS gap / insufficient data" while the latest GPS window could not be predicted; else null. Not rendered. */
    val gpsDataNote: String? = null,
)