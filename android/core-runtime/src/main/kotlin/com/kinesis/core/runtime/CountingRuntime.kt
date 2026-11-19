package com.kinesis.core.runtime

import com.kinesis.core.model.CountingEngine
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.EngineListener
import com.kinesis.core.model.FieldPolicy
import com.kinesis.core.model.FieldState
import com.kinesis.core.model.PersistedCounting
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.UnavailableReason
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Process-singleton owner of the counting state.
 *
 * Engine callbacks (any thread) and user actions are turned into pure state transformations that
 * a single consumer applies through [CountingStore], so they are applied in arrival order, one
 * atomic DataStore transaction each. The UI state is derived from the persisted state plus a few
 * transient live values; nothing is accumulated outside the reducer.
 *
 * Lifecycle: [start] records the request, the service then calls [onServiceStarted] (which starts
 * the engine), and [onServiceStopped] when it goes away. [stop] is the user's Stop.
 */
class CountingRuntime(
    val engine: CountingEngine,
    store: CountingStore,
    scope: CoroutineScope,
    private val elapsedRealtimeMs: () -> Long,
    private val evaluator: () -> RequirementEvaluation,
) : EngineListener {

    private data class Live(
        val serviceRunning: Boolean = false,
        val starting: Boolean = false,
        val speedMps: Float? = null,
        val accuracyM: Float? = null,
        val availability: EngineAvailability = EngineAvailability.Available,
        val engineUnavailable: UnavailableReason? = null,
        val failure: UnavailableReason? = null,
        val evaluation: RequirementEvaluation,
    )

    private class Mutation(val transform: (PersistedCounting) -> PersistedCounting, val done: CompletableDeferred<Unit>?)

    private val mutations = Channel<Mutation>(Channel.UNLIMITED)
    private val live = MutableStateFlow(
        Live(availability = engine.availability(), evaluation = evaluator()),
    )
    private val engineActive = AtomicBoolean(false)

    val state: StateFlow<CountingUiState> = combine(store.data, live) { persisted, l ->
        buildState(persisted, l)
    }.stateIn(scope, SharingStarted.Eagerly, buildState(PersistedCounting(), live.value))

    init {
        scope.launch {
            for (first in mutations) {
                // Apply everything already queued in one transaction, in arrival order.
                val batch = mutableListOf(first)
                while (true) batch += mutations.tryReceive().getOrNull() ?: break
                commit(store) { initial -> batch.fold(initial) { acc, m -> m.transform(acc) } }
                batch.forEach { it.done?.complete(Unit) }
            }
        }
    }

    /**
     * Applies one mutation. A failed write (for example a transient file lock on the DataStore
     * file) is retried, so a single I/O error cannot stop the consumer and silently freeze counting.
     */
    private suspend fun commit(store: CountingStore, transform: (PersistedCounting) -> PersistedCounting) {
        repeat(WRITE_ATTEMPTS) { attempt ->
            try {
                store.update(transform)
                return
            } catch (e: IOException) {
                if (attempt == WRITE_ATTEMPTS - 1) return // dropped; the next reading re-derives the session
                delay(WRITE_RETRY_DELAY_MS)
            }
        }
    }

    val isServiceRunning: Boolean get() = live.value.serviceRunning

    /** Re-reads permissions and engine availability. Clears an earlier start failure. */
    fun refreshAvailability() {
        live.update { it.copy(availability = engine.availability(), evaluation = evaluator(), failure = null) }
    }

    /**
     * Records a start request. Returns false (and publishes a Blocked state) when a required
     * permission or the engine itself is unavailable. The caller then starts the service.
     */
    fun start(): Boolean {
        refreshAvailability()
        val current = live.value
        val reason = current.evaluation.blockReason
            ?: (current.availability as? EngineAvailability.Unavailable)?.reason
        if (reason != null) {
            live.update { it.copy(failure = reason, starting = false) }
            return false
        }
        live.update { it.copy(starting = true, failure = null, engineUnavailable = null) }
        mutate { it.copy(monitoringRequested = true) }
        return true
    }

    /** The user pressed Stop: steps taken while stopped are excluded on the next start. */
    fun stop() {
        stopEngine()
        live.update { it.copy(starting = false, speedMps = null, accuracyM = null, engineUnavailable = null) }
        mutate { it.onUserStop() }
    }

    /** Zeroes the session values on both channels. Works whether or not the service runs. */
    fun resetSteps() {
        val now = elapsedRealtimeMs()
        mutate { it.reset(now) }
        engine.onReset()
    }

    /** The foreground service is up. Starts the engine once; repeated calls are no-ops. */
    fun onServiceStarted() {
        live.update { it.copy(serviceRunning = true, starting = false) }
        if (engineActive.compareAndSet(false, true)) engine.start(this)
    }

    /** The service is gone for any reason. Does not clear the monitoring request. */
    fun onServiceStopped() {
        stopEngine()
        live.update { it.copy(serviceRunning = false, starting = false, speedMps = null, accuracyM = null) }
    }

    /** Android refused to start the foreground service. */
    fun onStartFailed(reason: UnavailableReason) {
        stopEngine()
        live.update { it.copy(serviceRunning = false, starting = false, failure = reason) }
        mutate { it.copy(monitoringRequested = false) }
    }

    private fun stopEngine() {
        if (engineActive.compareAndSet(true, false)) engine.stop()
    }

    private fun mutate(transform: (PersistedCounting) -> PersistedCounting) {
        mutations.trySend(Mutation(transform, null))
    }

    /** Suspends until every mutation queued so far is committed to the store. */
    suspend fun awaitIdle() {
        val done = CompletableDeferred<Unit>()
        mutations.trySend(Mutation({ it }, done))
        done.await()
    }

    override fun onSteps(epoch: Long, cumulative: Double) = mutate { it.onSteps(epoch, cumulative) }

    override fun onDistance(epoch: Long, cumulativeM: Double) = mutate { it.onDistance(epoch, cumulativeM) }

    override fun onFix(speedMps: Float?, accuracyM: Float?) {
        live.update { it.copy(speedMps = speedMps, accuracyM = accuracyM, engineUnavailable = null) }
    }

    override fun onUnavailable(reason: UnavailableReason) {
        live.update { it.copy(engineUnavailable = reason) }
    }

    private fun buildState(persisted: PersistedCounting, l: Live): CountingUiState {
        val profile = engine.profile
        val unavailable = l.engineUnavailable ?: (l.availability as? EngineAvailability.Unavailable)?.reason
        val status = when {
            l.failure != null -> RunStatus.Blocked(l.failure)
            l.serviceRunning && l.engineUnavailable != null -> RunStatus.Blocked(l.engineUnavailable)
            l.serviceRunning -> RunStatus.Counting
            l.starting -> RunStatus.Starting
            persisted.monitoringRequested -> RunStatus.Interrupted
            unavailable == UnavailableReason.SENSOR_MISSING ||
                unavailable == UnavailableReason.PRECISE_LOCATION_REQUIRED -> RunStatus.Blocked(unavailable)
            else -> RunStatus.Stopped
        }
        fun <T> field(policy: FieldPolicy, value: T?): FieldState<T> = when (policy) {
            FieldPolicy.NOT_USED -> FieldState.NotUsed
            FieldPolicy.NOT_ENABLED -> FieldState.NotEnabled
            FieldPolicy.USED -> when {
                unavailable != null -> FieldState.Unavailable(unavailable)
                value != null -> FieldState.Value(value)
                else -> FieldState.Waiting
            }
        }
        val hasDistance = persisted.distanceM.epoch != null
        val hasSteps = persisted.steps.epoch != null
        return CountingUiState(
            runStatus = status,
            sessionSteps = persisted.steps.session.toLong(),
            stepsLabel = profile.stepsLabel,
            gpsSpeedMps = field(profile.gpsSpeed, l.speedMps),
            gpsAccuracyM = field(profile.gpsAccuracy, l.accuracyM),
            sessionDistanceM = field(profile.sessionDistance, if (hasDistance) persisted.distanceM.session else null),
            sensorTotalSinceBoot = field(
                profile.sensorTotalSinceBoot,
                if (hasSteps) persisted.steps.last.toLong() else null,
            ),
            activity = field(profile.activity, null as String?),
            movementVerdict = field(profile.movementVerdict, null as String?),
            requirements = l.evaluation.statuses,
            canStart = l.evaluation.canStart && l.availability is EngineAvailability.Available,
        )
    }

    private companion object {
        const val WRITE_ATTEMPTS = 3
        const val WRITE_RETRY_DELAY_MS = 50L
    }
}
