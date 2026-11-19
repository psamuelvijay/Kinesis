package com.kinesis.sensorfusion

import androidx.test.platform.app.InstrumentationRegistry
import com.kinesis.core.model.RunStatus
import com.kinesis.core.runtime.CountingRuntime
import com.kinesis.core.runtime.CountingStore
import com.kinesis.core.runtime.evaluateRequirements
import com.kinesis.engine.physical.PhysicalStepsCountingEngine
import com.kinesis.engine.physical.StepCounterFeed
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/**
 * The App B engine and runtime on the device with a fake step-counter feed (the emulator has no
 * TYPE_STEP_COUNTER). Uses its own DataStore file, so the app's state is untouched.
 */
class FakeFeedRuntimeTest {

    private class FakeFeed : StepCounterFeed {
        var cb: ((Float) -> Unit)? = null
        override val isAvailable = true
        override fun start(cb: (Float) -> Unit) { this.cb = cb }
        override fun stop() { cb = null }
    }

    private fun build(file: File, feed: FakeFeed, scope: CoroutineScope, boot: Long): CountingRuntime {
        val engine = PhysicalStepsCountingEngine(feed) { boot }
        return CountingRuntime(
            engine = engine,
            store = CountingStore.create(file, scope),
            scope = scope,
            elapsedRealtimeMs = { 0L },
            evaluator = { evaluateRequirements(engine.requirements, engine.requirements, 34, true) },
        )
    }

    private suspend fun CountingRuntime.awaitSteps(n: Long) {
        awaitIdle()
        withTimeout(5_000) { state.first { it.sessionSteps == n } }
    }

    @Test
    fun countResetAndRestartWithoutDuplicates(): Unit = runBlocking {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(ctx.cacheDir, "fake_feed_test.preferences_pb").also { it.delete() }

        val scope1 = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val feed1 = FakeFeed()
        val first = build(file, feed1, scope1, boot = 3)
        first.start()
        first.onServiceStarted()
        feed1.cb!!(5_000f)
        feed1.cb!!(5_020f)
        first.awaitSteps(20)
        first.resetSteps()
        first.awaitSteps(0)
        feed1.cb!!(5_027f)
        first.awaitSteps(7)
        scope1.coroutineContext[Job]!!.cancelAndJoin() // simulated process death

        val scope2 = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val feed2 = FakeFeed()
        val second = build(file, feed2, scope2, boot = 3)
        second.awaitSteps(7)
        assertEquals(RunStatus.Interrupted, second.state.value.runStatus)
        second.start()
        second.onServiceStarted()
        feed2.cb!!(5_027f) // re-registration repeats the current total
        second.awaitSteps(7)
        feed2.cb!!(5_030f)
        second.awaitSteps(10)
        scope2.coroutineContext[Job]!!.cancelAndJoin()
        file.delete()
    }
}