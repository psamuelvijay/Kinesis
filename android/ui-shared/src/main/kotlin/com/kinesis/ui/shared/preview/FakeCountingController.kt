package com.kinesis.ui.shared.preview

import com.kinesis.core.model.CountingController
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.FieldPolicy
import com.kinesis.core.model.FieldState
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RequirementStatus
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.ui.shared.PermissionBridge
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/** Deterministic states for previews, tests and the M0 app shells. Counts nothing by itself. */
object FakeStates {
    private fun <T> field(policy: FieldPolicy, live: Boolean, value: T): FieldState<T> = when (policy) {
        FieldPolicy.USED -> if (live) FieldState.Value(value) else FieldState.Waiting
        FieldPolicy.NOT_USED -> FieldState.NotUsed
        FieldPolicy.NOT_ENABLED -> FieldState.NotEnabled
    }

    fun requirements(profile: MethodProfile, granted: Boolean = true): List<RequirementStatus> {
        val required = if (profile.gpsSpeed == FieldPolicy.USED) {
            listOf(RuntimeRequirement.FINE_LOCATION, RuntimeRequirement.LOCATION_SERVICES)
        } else {
            listOf(RuntimeRequirement.ACTIVITY_RECOGNITION)
        }
        return (required + RuntimeRequirement.NOTIFICATIONS_OPTIONAL).map { RequirementStatus(it, granted) }
    }

    fun state(
        profile: MethodProfile,
        runStatus: RunStatus,
        steps: Long,
        permissionsGranted: Boolean = true,
    ): CountingUiState {
        val live = runStatus == RunStatus.Counting
        return CountingUiState(
            runStatus = runStatus,
            sessionSteps = steps,
            stepsLabel = profile.stepsLabel,
            gpsSpeedMps = field(profile.gpsSpeed, live, 1.4f),
            gpsAccuracyM = field(profile.gpsAccuracy, live, 6f),
            sessionDistanceM = field(profile.sessionDistance, live, 812.0),
            sensorTotalSinceBoot = field(profile.sensorTotalSinceBoot, live, 48_213L),
            activity = field(profile.activity, live, "Walking"),
            movementVerdict = field(profile.movementVerdict, live, "Consistent"),
            requirements = requirements(profile, permissionsGranted),
            canStart = permissionsGranted,
        )
    }
}

class FakeCountingController(
    override val profile: MethodProfile,
    initial: CountingUiState = FakeStates.state(profile, RunStatus.Stopped, 0L),
) : CountingController {
    private val _state = MutableStateFlow(initial)
    override val state: StateFlow<CountingUiState> = _state.asStateFlow()

    override fun start() = _state.update { FakeStates.state(profile, RunStatus.Counting, it.sessionSteps) }
    override fun stop() = _state.update { FakeStates.state(profile, RunStatus.Stopped, it.sessionSteps) }
    override fun resetSteps() = _state.update { it.copy(sessionSteps = 0L) }
    override fun refreshAvailability() = Unit
}

/** Does nothing; replaced by an Activity-backed bridge when real permissions are wired. */
object NoOpPermissionBridge : PermissionBridge {
    override fun requestPermissions(requirements: List<RuntimeRequirement>) = Unit
    override fun openAppSettings() = Unit
    override fun openLocationSettings() = Unit
    override fun openBatterySettings() = Unit
    override fun isPermanentlyDenied(requirement: RuntimeRequirement) = false
}
