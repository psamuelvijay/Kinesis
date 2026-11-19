package com.kinesis.ui.shared

import androidx.lifecycle.ViewModel
import com.kinesis.core.model.CountingController
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.RuntimeRequirement
import kotlinx.coroutines.flow.StateFlow

/** Holds no counting state of its own; it only exposes the controller's state to the UI. */
class CountingViewModel(private val controller: CountingController) : ViewModel() {
    val profile = controller.profile
    val state: StateFlow<CountingUiState> = controller.state

    /** True from a Start tap that needed permissions until the permission result arrives. */
    private var startPending = false

    fun start() = controller.start()

    /**
     * Start tapped by the user. Missing runtime permissions are requested first; when the request
     * returns, the original start runs once if they were granted. Repeated taps while a request or
     * a start is in flight are ignored.
     */
    fun startWithPermissions(bridge: PermissionBridge) {
        if (startPending || isActive()) return
        controller.refreshAvailability()
        val missing = missingRuntimePermissions()
        if (missing.isEmpty()) {
            controller.start()
            return
        }
        startPending = true
        bridge.requestPermissions(missing)
    }

    /** Called when a permission request returns. Continues a pending start exactly once. */
    fun onPermissionResult() {
        controller.refreshAvailability()
        if (!startPending) return
        startPending = false
        // Granted: start. Denied: start() publishes the blocked state, so the permission card shows.
        if (!isActive()) controller.start()
    }

    fun stop() {
        startPending = false
        controller.stop()
    }

    fun resetSteps() = controller.resetSteps()
    fun refreshAvailability() = controller.refreshAvailability()

    private fun isActive() = state.value.runStatus.let { it == RunStatus.Counting || it == RunStatus.Starting }

    private fun missingRuntimePermissions(): List<RuntimeRequirement> =
        state.value.requirements
            .filter { !it.granted }
            .map { it.requirement }
            .filter { it != RuntimeRequirement.NOTIFICATIONS_OPTIONAL && it != RuntimeRequirement.LOCATION_SERVICES }
}
