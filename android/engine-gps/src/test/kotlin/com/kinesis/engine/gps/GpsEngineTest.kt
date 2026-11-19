package com.kinesis.engine.gps

import com.kinesis.core.model.CountingEngine
import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.EngineListener
import com.kinesis.core.model.UnavailableReason
import org.junit.Test
import kotlin.math.cos
import kotlin.test.assertEquals
import kotlin.test.assertTrue

private const val SECOND = 1_000_000_000L
private const val METRE_IN_DEG_LAT = 1.0 / 111_195.0

private fun fix(t: Int, northM: Double, accuracy: Float? = 5f, eastM: Double = 0.0) = GpsFix(
    elapsedRealtimeNanos = t * SECOND,
    latitude = 10.0 + northM * METRE_IN_DEG_LAT,
    longitude = 20.0 + eastM * METRE_IN_DEG_LAT / cos(Math.toRadians(10.0)),
    accuracyM = accuracy,
    speedMps = null,
)

class GpsStepEstimatorTest {
    @Test
    fun oneDegreeOfLatitudeIsAbout111195Metres() {
        val d = haversineM(0.0, 0.0, 1.0, 0.0)
        assertEquals(111_195.0, d, 111_195.0 * 0.001)
    }

    @Test
    fun walkingAtSevenMetresPerSecondAccumulatesPathAndSteps() {
        val e = GpsStepEstimator()
        for (t in 0..10) e.onFix(fix(t, northM = t * 7.0))
        // The newest fix is held back one step, so 9 of the 10 segments are committed.
        assertEquals(63.0, e.cumulativeDistanceM, 0.5)
        assertEquals(e.cumulativeDistanceM / PROVISIONAL_STRIDE_M, e.cumulativeSteps, 1e-9)
    }

    @Test
    fun fixesWithPoorAccuracyAreDropped() {
        val e = GpsStepEstimator()
        e.onFix(fix(0, 0.0))
        e.onFix(fix(1, 5.0, accuracy = 80f)) // dropped
        e.onFix(fix(2, 10.0))
        e.onFix(fix(3, 15.0))
        assertEquals(10.0, e.cumulativeDistanceM, 0.1)
    }

    @Test
    fun invalidCoordinatesAreDropped() {
        val e = GpsStepEstimator()
        e.onFix(fix(0, 0.0))
        e.onFix(GpsFix(1 * SECOND, Double.NaN, 20.0, 5f, null))
        e.onFix(GpsFix(2 * SECOND, 95.0, 20.0, 5f, null))
        e.onFix(fix(3, 3.0))
        e.onFix(fix(4, 4.0))
        assertEquals(3.0, e.cumulativeDistanceM, 0.1)
    }

    @Test
    fun singleTeleportFixIsDroppedAndAddsNothing() {
        val e = GpsStepEstimator()
        e.onFix(fix(0, 0.0))
        e.onFix(fix(1, 2.0))
        e.onFix(fix(2, 5_000.0)) // implies 4998 m/s to both neighbours
        e.onFix(fix(3, 6.0))
        e.onFix(fix(4, 8.0))
        e.onFix(fix(5, 10.0))
        assertTrue(e.cumulativeDistanceM < 20.0, "was ${e.cumulativeDistanceM}")
        assertEquals(8.0, e.cumulativeDistanceM, 0.3)
    }

    @Test
    fun gapsLongerThanTenSecondsAreNotBridged() {
        val e = GpsStepEstimator()
        e.onFix(fix(0, 0.0))
        e.onFix(fix(1, 5.0))
        e.onFix(fix(20, 500.0)) // 19 s later, 495 m away
        e.onFix(fix(21, 505.0))
        e.onFix(fix(22, 510.0))
        assertEquals(10.0, e.cumulativeDistanceM, 0.3) // 5 m before the gap + 5 m after it
    }

    @Test
    fun outOfOrderFixIsIgnored() {
        val e = GpsStepEstimator()
        e.onFix(fix(5, 0.0))
        e.onFix(fix(4, 100.0))
        e.onFix(fix(6, 4.0))
        e.onFix(fix(7, 8.0))
        assertEquals(4.0, e.cumulativeDistanceM, 0.3) // 5 to 6 committed; the newest fix is held back
    }

    /** Documents the known weakness: no jitter gate, so stationary GPS noise creates phantom steps. */
    @Test
    fun stationaryJitterProducesPhantomSteps() {
        val e = GpsStepEstimator()
        for (t in 0..60) {
            val wobble = if (t % 2 == 0) 0.0 else 3.0
            e.onFix(fix(t, wobble))
        }
        assertTrue(e.cumulativeSteps > 100.0, "phantom steps expected, was ${e.cumulativeSteps}")
    }
}

private class FakeSource(var availability: EngineAvailability = EngineAvailability.Available) : GpsFixSource {
    var onFix: ((GpsFix) -> Unit)? = null
    var onProblem: ((UnavailableReason) -> Unit)? = null
    var starts = 0
    var stops = 0
    override fun availability() = availability
    override fun start(onFix: (GpsFix) -> Unit, onProblem: (UnavailableReason) -> Unit) {
        starts++
        this.onFix = onFix
        this.onProblem = onProblem
    }
    override fun stop() {
        stops++
    }
}

private class Recorder : EngineListener {
    val steps = mutableListOf<Pair<Long, Double>>()
    val distances = mutableListOf<Pair<Long, Double>>()
    var fixes = 0
    var unavailable: UnavailableReason? = null
    override fun onSteps(epoch: Long, cumulative: Double) { steps += epoch to cumulative }
    override fun onDistance(epoch: Long, cumulativeM: Double) { distances += epoch to cumulativeM }
    override fun onFix(speedMps: Float?, accuracyM: Float?) { fixes++ }
    override fun onUnavailable(reason: UnavailableReason) { unavailable = reason }
}

class GpsCountingEngineTest {
    @Test
    fun startEmitsZeroForTheNewEpochThenFollowsFixes() {
        val source = FakeSource()
        val engine: CountingEngine = GpsCountingEngine(source, epochProvider = { 99L })
        val rec = Recorder()
        engine.start(rec)
        assertEquals(listOf(99L to 0.0), rec.steps)
        for (t in 0..5) source.onFix!!(fix(t, t * 5.0))
        assertEquals(6, rec.fixes)
        assertTrue(rec.steps.last().second > 0.0)
        assertTrue(rec.steps.all { it.first == 99L })
    }

    @Test
    fun repeatedStartRegistersTheSourceOnce() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source)
        engine.start(Recorder())
        engine.start(Recorder())
        assertEquals(1, source.starts)
        engine.stop()
        engine.stop()
        assertEquals(1, source.stops)
    }

    @Test
    fun sourceProblemIsForwarded() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source)
        val rec = Recorder()
        engine.start(rec)
        source.onProblem!!(UnavailableReason.LOCATION_SERVICES_OFF)
        assertEquals(UnavailableReason.LOCATION_SERVICES_OFF, rec.unavailable)
    }

    @Test
    fun availabilityComesFromTheSource() {
        val source = FakeSource(EngineAvailability.Unavailable(UnavailableReason.PRECISE_LOCATION_REQUIRED))
        assertEquals(source.availability, GpsCountingEngine(source).availability())
    }
}
