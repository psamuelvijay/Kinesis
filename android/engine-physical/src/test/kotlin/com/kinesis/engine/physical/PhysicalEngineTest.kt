package com.kinesis.engine.physical

import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.EngineListener
import com.kinesis.core.model.UnavailableReason
import org.junit.Test
import kotlin.test.assertEquals

private class FakeFeed(override val isAvailable: Boolean = true) : StepCounterFeed {
    var cb: ((Float) -> Unit)? = null
    var starts = 0
    var stops = 0
    override fun start(cb: (Float) -> Unit) {
        starts++
        this.cb = cb
    }
    override fun stop() {
        stops++
    }
}

private class Recorder : EngineListener {
    val steps = mutableListOf<Pair<Long, Double>>()
    var unavailable: UnavailableReason? = null
    override fun onSteps(epoch: Long, cumulative: Double) { steps += epoch to cumulative }
    override fun onDistance(epoch: Long, cumulativeM: Double) = Unit
    override fun onFix(speedMps: Float?, accuracyM: Float?) = Unit
    override fun onUnavailable(reason: UnavailableReason) { unavailable = reason }
}

class PhysicalEngineTest {
    @Test
    fun forwardsCumulativeReadingsWithTheBootEpoch() {
        val feed = FakeFeed()
        val engine = PhysicalStepsCountingEngine(feed) { 5L }
        val rec = Recorder()
        engine.start(rec)
        feed.cb!!(1000f)
        feed.cb!!(1012f)
        assertEquals(listOf(5L to 1000.0, 5L to 1012.0), rec.steps)
    }

    @Test
    fun missingSensorIsUnavailableAndNeverStartsTheFeed() {
        val feed = FakeFeed(isAvailable = false)
        val engine = PhysicalStepsCountingEngine(feed) { 0L }
        assertEquals(EngineAvailability.Unavailable(UnavailableReason.SENSOR_MISSING), engine.availability())
        val rec = Recorder()
        engine.start(rec)
        assertEquals(UnavailableReason.SENSOR_MISSING, rec.unavailable)
        assertEquals(0, feed.starts)
    }

    @Test
    fun repeatedStartRegistersOnce() {
        val feed = FakeFeed()
        val engine = PhysicalStepsCountingEngine(feed) { 0L }
        engine.start(Recorder())
        engine.start(Recorder())
        engine.stop()
        engine.stop()
        assertEquals(1, feed.starts)
        assertEquals(1, feed.stops)
    }
}
