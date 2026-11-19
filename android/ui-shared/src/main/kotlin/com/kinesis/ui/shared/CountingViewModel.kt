package com.kinesis.ui.shared

import androidx.lifecycle.ViewModel
import com.kinesis.core.model.CountingController
import com.kinesis.core.model.CountingUiState
import kotlinx.coroutines.flow.StateFlow

/** Holds no counting state of its own; it only exposes the controller's state to the UI. */
class CountingViewModel(private val controller: CountingController) : ViewModel() {
    val profile = controller.profile
    val state: StateFlow<CountingUiState> = controller.state

    fun start() = controller.start()
    fun stop() = controller.stop()
    fun resetSteps() = controller.resetSteps()
    fun refreshAvailability() = controller.refreshAvailability()
}
