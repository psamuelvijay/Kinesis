package com.kinesis.core.runtime

import com.kinesis.core.model.CountingEngine
import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.EngineListener
import com.kinesis.core.model.FieldState
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.core.model.UnavailableReason
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.PersistedCounting
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.yield
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.rules.Timeout
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

private class FakeEngine(var availability: EngineAvailability = EngineAvailability.Available) : CountingEngine {
    override val profile = MethodProfile.SENSOR_FUSION
    override val requirements = setOf(RuntimeRequirement.ACTIVITY_RECOGNITION, RuntimeRequirement.NOTIFICATIONS_OPTIONAL)
    var listener: EngineListener? = null
    var starts = 0
    var stops = 0
    var resets = 0
    override fun availability() = availability
    override fun start(listener: EngineListener) {
        starts++
        this.listener = listener
    }
    override fun stop() {
        stops++
        listener = null
    }
    override fun onReset() {
        resets++
    }
}

private class Harness(file: File, val engine: FakeEngine, granted: Boolean = true) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val store = CountingStore.create(file, scope)
    val runtime = CountingRuntime(
        engine = engine,
        store = store,
        scope = scope,
        elapsedRealtimeMs = { 42L },
        evaluator = {
            evaluateRequirements(
                required = engine.requirements,
                granted = if (granted) engine.requirements else emptySet(),
                sdkInt = 34,
                locationServicesOn = true,
            )
        },
    )

    fun running() {
        assertTrue(runtime.start())
        runtime.onServiceStarted()
    }

    /** Waits for queued writes, then for the derived UI state to catch up. */
    suspend fun state(until: (CountingUiState) -> Boolean = { true }): CountingUiState {
        withTimeout(5_000) { runtime.awaitIdle() }
        return try {
            withTimeout(2_000) { runtime.state.first(until) }
        } catch (e: TimeoutCancellationException) {
            runtime.state.value
        }
    }

    suspend fun persisted(): PersistedCounting {
        withTimeout(5_000) { runtime.awaitIdle() }
        return store.data.first()
    }

    suspend fun close() {
        withTimeout(5_000) { runtime.awaitIdle() }
        scope.coroutineContext[kotlinx.coroutines.Job]!!.cancelAndJoin()
    }
}

class CountingRuntimeTest {
    @get:Rule
    val folder = TemporaryFolder()

    @get:Rule
    val timeout: Timeout = Timeout.seconds(30)

    private fun file() = File(folder.root, "counting_state.preferences_pb")

    @Test
    fun countingIncrementsSession() = runBlocking {
        val h = Harness(file(), FakeEngine())
        h.running()
        listOf(100.0, 103.0, 110.0).forEach { h.engine.listener!!.onSteps(1, it) }
        assertEquals(10L, h.state { it.sessionSteps == 10L }.sessionSteps)
        assertEquals(RunStatus.Counting, h.state { it.runStatus == RunStatus.Counting }.runStatus)
        assertEquals(FieldState.Value(110L), h.state { it.sensorTotalSinceBoot == FieldState.Value(110L) }.sensorTotalSinceBoot)
        h.close()
    }

    @Test
    fun resetChangesOnlySessionAndKeepsCumulativeReadings() = runBlocking {
        val h = Harness(file(), FakeEngine())
        h.running()
        listOf(100.0, 110.0).forEach { h.engine.listener!!.onSteps(1, it) }
        h.runtime.resetSteps()
        assertEquals(0L, h.state { it.sessionSteps == 0L }.sessionSteps)
        val persisted = h.persisted()
        assertEquals(110.0, persisted.steps.last)
        assertEquals(110.0, persisted.steps.baseline)
        assertEquals(1, h.engine.resets)
        assertEquals(1, persisted.resetCount)
        assertEquals(42L, persisted.lastResetElapsedMs)
        h.engine.listener!!.onSteps(1, 115.0)
        assertEquals(5L, h.state { it.sessionSteps == 5L }.sessionSteps)
        h.close()
    }

    @Test
    fun resetWorksWhileStopped() = runBlocking {
        val h = Harness(file(), FakeEngine())
        h.running()
        h.engine.listener!!.onSteps(1, 5.0)
        h.engine.listener!!.onSteps(1, 9.0)
        h.runtime.stop()
        h.runtime.onServiceStopped()
        h.runtime.resetSteps()
        assertEquals(0L, h.state { it.sessionSteps == 0L }.sessionSteps)
        assertEquals(RunStatus.Stopped, h.state { it.runStatus == RunStatus.Stopped }.runStatus)
        assertEquals(1, h.persisted().resetCount)
        h.close()
    }

    @Test
    fun processDeathKeepsStepsAndDoesNotDoubleCountRepeatedReading() = runBlocking {
        val f = file()
        val first = Harness(f, FakeEngine())
        first.running()
        listOf(100.0, 110.0).forEach { first.engine.listener!!.onSteps(7, it) }
        first.runtime.resetSteps()
        first.engine.listener!!.onSteps(7, 114.0)
        assertEquals(4L, first.state { it.sessionSteps == 4L }.sessionSteps)
        first.close() // "process death": the service never reported stopping

        val second = Harness(f, FakeEngine())
        assertEquals(4L, second.state { it.sessionSteps == 4L }.sessionSteps)
        assertEquals(RunStatus.Interrupted, second.state { it.runStatus == RunStatus.Interrupted }.runStatus)
        second.running()
        second.engine.listener!!.onSteps(7, 114.0) // re-registration delivers the same total again
        assertEquals(4L, second.state { it.sessionSteps == 4L }.sessionSteps)
        second.engine.listener!!.onSteps(7, 116.0)
        assertEquals(6L, second.state { it.sessionSteps == 6L }.sessionSteps)
        assertEquals(RunStatus.Counting, second.state { it.runStatus == RunStatus.Counting }.runStatus)
        second.close()
    }

    @Test
    fun rebootWithLargerFirstValueAddsNoPhantomSteps() = runBlocking {
        val h = Harness(file(), FakeEngine())
        h.running()
        listOf(100.0, 110.0).forEach { h.engine.listener!!.onSteps(1, it) }
        h.engine.listener!!.onSteps(2, 500.0) // new boot, counter restarted but first reading is larger
        assertEquals(10L, h.state { it.sessionSteps == 10L }.sessionSteps)
        h.engine.listener!!.onSteps(2, 503.0)
        assertEquals(13L, h.state { it.sessionSteps == 13L }.sessionSteps)
        h.close()
    }

    @Test
    fun stepsWhileUserStoppedAreExcluded() = runBlocking {
        val h = Harness(file(), FakeEngine())
        h.running()
        listOf(100.0, 110.0).forEach { h.engine.listener!!.onSteps(1, it) }
        h.runtime.stop()
        h.runtime.onServiceStopped()
        assertFalse(h.persisted().monitoringRequested)
        h.running()
        h.engine.listener!!.onSteps(1, 150.0)
        assertEquals(10L, h.state { it.sessionSteps == 10L }.sessionSteps)
        h.engine.listener!!.onSteps(1, 155.0)
        assertEquals(15L, h.state { it.sessionSteps == 15L }.sessionSteps)
        h.close()
    }

    @Test
    fun concurrentResetAndManyReadingsKeepSessionConsistent() = runBlocking {
        val h = Harness(file(), FakeEngine())
        h.running()
        val listener = h.engine.listener!!
        var lastAtReset = -1
        var current = 0
        val producer = launch {
            for (i in 0..1000) {
                current = i
                listener.onSteps(1, i.toDouble())
                if (i % 7 == 0) yield()
            }
        }
        val resetter = launch {
            repeat(50) { yield() }
            lastAtReset = current
            h.runtime.resetSteps()
        }
        producer.join()
        resetter.join()
        assertEquals((1000 - lastAtReset).toLong(), h.state { it.sessionSteps == (1000 - lastAtReset).toLong() }.sessionSteps)
        assertEquals(1000.0, h.persisted().steps.last)
        h.close()
    }

    @Test
    fun startIsRefusedWhenRequirementMissing() = runBlocking {
        val h = Harness(file(), FakeEngine(), granted = false)
        assertFalse(h.runtime.start())
        val state = h.state { it.runStatus is RunStatus.Blocked }
        assertEquals(RunStatus.Blocked(UnavailableReason.PERMISSION_DENIED), state.runStatus)
        assertFalse(state.canStart)
        assertEquals(0, h.engine.starts)
        assertFalse(h.persisted().monitoringRequested)
        h.close()
    }

    @Test
    fun missingSensorBlocksStartWithReason() = runBlocking {
        val engine = FakeEngine(EngineAvailability.Unavailable(UnavailableReason.SENSOR_MISSING))
        val h = Harness(file(), engine)
        val state = h.state { it.runStatus is RunStatus.Blocked }
        assertFalse(state.canStart)
        assertEquals(RunStatus.Blocked(UnavailableReason.SENSOR_MISSING), state.runStatus)
        assertEquals(FieldState.Unavailable(UnavailableReason.SENSOR_MISSING), state.sensorTotalSinceBoot)
        assertFalse(h.runtime.start())
        h.close()
    }

    @Test
    fun serviceStartFailureIsPublishedNotThrown() = runBlocking {
        val h = Harness(file(), FakeEngine())
        assertTrue(h.runtime.start())
        h.runtime.onStartFailed(UnavailableReason.SERVICE_BLOCKED)
        assertEquals(RunStatus.Blocked(UnavailableReason.SERVICE_BLOCKED), h.state { it.runStatus == RunStatus.Blocked(UnavailableReason.SERVICE_BLOCKED) }.runStatus)
        assertFalse(h.persisted().monitoringRequested)
        h.close()
    }

    @Test
    fun repeatedServiceStartRegistersEngineOnce() = runBlocking {
        val h = Harness(file(), FakeEngine())
        h.running()
        h.runtime.start()
        h.runtime.onServiceStarted()
        h.runtime.onServiceStarted()
        assertEquals(1, h.engine.starts)
        h.runtime.onServiceStopped()
        assertEquals(1, h.engine.stops)
        h.close()
    }

    @Test
    fun interruptedFlagIsOnlySetWhileMonitoringWasRequested() = runBlocking {
        val h = Harness(file(), FakeEngine())
        assertIs<RunStatus.Stopped>(h.state().runStatus)
        h.close()
    }
}

class RequirementsTest {
    private val required = setOf(
        RuntimeRequirement.FINE_LOCATION,
        RuntimeRequirement.LOCATION_SERVICES,
        RuntimeRequirement.NOTIFICATIONS_OPTIONAL,
    )

    @Test
    fun allMetCanStart() {
        val e = evaluateRequirements(required, setOf(RuntimeRequirement.FINE_LOCATION, RuntimeRequirement.NOTIFICATIONS_OPTIONAL), 34, true)
        assertTrue(e.canStart)
    }

    @Test
    fun deniedNotificationsNeverBlock() {
        val e = evaluateRequirements(required, setOf(RuntimeRequirement.FINE_LOCATION), 34, true)
        assertTrue(e.canStart)
        assertFalse(e.statuses.first { it.requirement == RuntimeRequirement.NOTIFICATIONS_OPTIONAL }.granted)
    }

    @Test
    fun belowAndroid13NotificationsAreAlwaysMet() {
        val e = evaluateRequirements(required, setOf(RuntimeRequirement.FINE_LOCATION), 29, true)
        assertTrue(e.statuses.first { it.requirement == RuntimeRequirement.NOTIFICATIONS_OPTIONAL }.granted)
    }

    @Test
    fun locationServicesOffBlocksWithOwnReason() {
        val e = evaluateRequirements(required, setOf(RuntimeRequirement.FINE_LOCATION), 34, false)
        assertEquals(listOf(RuntimeRequirement.LOCATION_SERVICES), e.missing)
        assertEquals(UnavailableReason.LOCATION_SERVICES_OFF, e.blockReason)
    }

    @Test
    fun missingPermissionBlocks() {
        val e = evaluateRequirements(required, emptySet(), 34, true)
        assertEquals(listOf(RuntimeRequirement.FINE_LOCATION), e.missing)
        assertEquals(UnavailableReason.PERMISSION_DENIED, e.blockReason)
        assertFalse(e.canStart)
    }
}
