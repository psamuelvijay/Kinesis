package com.kinesis.ui.shared

import com.kinesis.core.model.CountingController
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.ui.shared.preview.FakeStates
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.junit.Test
import kotlin.test.assertEquals

class StartWithPermissionsTest {
    private val profile = MethodProfile.GPS_ONLY

    private class Controller(override val profile: MethodProfile, initial: CountingUiState) : CountingController {
        val flow = MutableStateFlow(initial)
        override val state: StateFlow<CountingUiState> = flow
        var starts = 0
        override fun start() { starts++; flow.value = flow.value.copy(runStatus = RunStatus.Starting) }
        override fun stop() = Unit
        override fun resetSteps() = Unit
        override fun refreshAvailability() = Unit
    }

    private class Bridge : PermissionBridge {
        var requests = 0
        override fun requestPermissions(requirements: List<RuntimeRequirement>) { requests++ }
        override fun openAppSettings() = Unit
        override fun openLocationSettings() = Unit
        override fun openBatterySettings() = Unit
        override fun isPermanentlyDenied(requirement: RuntimeRequirement) = false
    }

    private fun missing() = FakeStates.state(profile, RunStatus.Stopped, 0L, permissionsGranted = false)
    private fun granted() = FakeStates.state(profile, RunStatus.Stopped, 0L, permissionsGranted = true)

    @Test
    fun grantedPermissionsStartImmediatelyWithoutRequest() {
        val c = Controller(profile, granted()); val b = Bridge(); val vm = CountingViewModel(c)
        vm.startWithPermissions(b)
        assertEquals(0, b.requests); assertEquals(1, c.starts)
    }

    @Test
    fun missingPermissionsRequestThenStartOnceOnGrant() {
        val c = Controller(profile, missing()); val b = Bridge(); val vm = CountingViewModel(c)
        vm.startWithPermissions(b)
        assertEquals(1, b.requests); assertEquals(0, c.starts)
        c.flow.value = granted()
        vm.onPermissionResult()
        vm.onPermissionResult() // e.g. the notification prompt returning afterwards
        assertEquals(1, c.starts)
    }

    @Test
    fun doubleTapWhileRequestPendingRequestsOnce() {
        val c = Controller(profile, missing()); val b = Bridge(); val vm = CountingViewModel(c)
        vm.startWithPermissions(b); vm.startWithPermissions(b)
        assertEquals(1, b.requests)
    }

    @Test
    fun denialRunsStartOnceSoBlockedStateIsPublishedAndTapWorksAgain() {
        val c = Controller(profile, missing()); val b = Bridge(); val vm = CountingViewModel(c)
        vm.startWithPermissions(b)
        c.flow.value = missing().copy(runStatus = RunStatus.Stopped)
        vm.onPermissionResult()
        assertEquals(1, c.starts) // controller.start() publishes the blocked state; no engine starts
        c.flow.value = missing()
        vm.startWithPermissions(b) // no dead end: Start asks again
        assertEquals(2, b.requests)
    }

    @Test
    fun startWhileAlreadyStartingIsIgnored() {
        val c = Controller(profile, granted()); val b = Bridge(); val vm = CountingViewModel(c)
        vm.startWithPermissions(b); vm.startWithPermissions(b)
        assertEquals(1, c.starts)
    }

    @Test
    fun resultWithoutPendingStartDoesNotStart() {
        val c = Controller(profile, granted()); val vm = CountingViewModel(c)
        vm.onPermissionResult()
        assertEquals(0, c.starts)
    }
}
