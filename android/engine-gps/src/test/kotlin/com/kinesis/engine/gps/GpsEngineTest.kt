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

private fun fix(t: Int) = GpsFix(t * SECOND, 10.0, 20.0, 5.0, 1.0)

/** Closes window t for a fix at t seconds; raw null means an excluded window. */
private class FakeEstimator(private val raw: Double? = 7.0) : WindowEstimator {
    override fun onFix(fix: GpsFix): List<WindowResult> {
        val k = windowIndexOf(fix.elapsedRealtimeNanos / 1e6)
        return listOf(
            if (raw == null) WindowResult(k, 0.0, WindowStatus.LONG_GAP_OVERLAP, null, null, 0.0, 0.0)
            else WindowResult(k, 0.0, WindowStatus.PREDICTED, null, raw, raw.coerceAtLeast(0.0), 1.0),
        )
    }
}

class HaversineTest {
    @Test
    fun oneDegreeOfLatitudeIsAbout111195Metres() {
        assertEquals(111_195.0, haversineM(0.0, 0.0, 1.0, 0.0), 111_195.0 * 0.001)
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
    val windows = mutableListOf<Long>()
    val status = mutableListOf<Boolean>()
    override fun onSteps(epoch: Long, cumulative: Double) { steps += epoch to cumulative }
    override fun onDistance(epoch: Long, cumulativeM: Double) { distances += epoch to cumulativeM }
    override fun onFix(speedMps: Float?, accuracyM: Float?) { fixes++ }
    override fun onUnavailable(reason: UnavailableReason) { unavailable = reason }
    override fun onWindowCounted(index: Long) { windows += index }
    override fun onGpsDataStatus(insufficient: Boolean) { status += insufficient }
}

class GpsCountingEngineTest {
    @Test
    fun startEmitsZeroForTheNewEpochThenFollowsFixes() {
        val source = FakeSource()
        val engine: CountingEngine = GpsCountingEngine(source, { FakeEstimator() }, epochProvider = { 99L })
        val rec = Recorder()
        engine.start(rec)
        assertEquals(listOf(99L to 0.0), rec.steps)
        for (t in 0..5) source.onFix!!(fix(t * 5))
        assertEquals(6, rec.fixes)
        assertTrue(rec.steps.last().second > 0.0)
        assertTrue(rec.steps.all { it.first == 99L })
    }

    @Test
    fun repeatedStartRegistersTheSourceOnce() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source, { FakeEstimator() })
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
        val engine = GpsCountingEngine(source, { FakeEstimator() })
        val rec = Recorder()
        engine.start(rec)
        source.onProblem!!(UnavailableReason.LOCATION_SERVICES_OFF)
        assertEquals(UnavailableReason.LOCATION_SERVICES_OFF, rec.unavailable)
    }

    @Test
    fun availabilityComesFromTheSource() {
        val source = FakeSource(EngineAvailability.Unavailable(UnavailableReason.PRECISE_LOCATION_REQUIRED))
        assertEquals(source.availability, GpsCountingEngine(source, { FakeEstimator() }).availability())
    }
}

class RealPipelineRestartTest {
    private val model by lazy {
        RandomForestModel.parse(java.io.File("src/main/assets/gps_rf_model.bin").readBytes())
    }

    private fun walk(source: FakeSource, fromSec: Int, toSec: Int) {
        for (t in fromSec..toSec) {
            source.onFix!!(GpsFix(t * SECOND, 10.0 + (t - fromSec) * 1.4 / 111_195.0, 20.0, 1.4, 5.0))
        }
    }

    @Test
    fun restartWithRestoredCursorStillCountsNewWindowsAndNeverRecounts() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source, { GpsWindowPipeline.clockAligned(model) })
        val rec1 = Recorder()
        engine.start(rec1)
        walk(source, 500, 560)
        assertTrue(rec1.windows.isNotEmpty())
        assertEquals(rec1.windows.sorted(), rec1.windows)
        assertEquals(rec1.windows.size, rec1.windows.toSet().size)
        assertTrue(rec1.windows.all { it >= 100L })
        val cursor = rec1.windows.last()
        engine.stop()

        // Process death: a fresh engine restored from the persisted cursor, later on the same clock.
        val source2 = FakeSource()
        val engine2 = GpsCountingEngine(source2, { GpsWindowPipeline.clockAligned(model) })
        engine2.restoreCountedWindow(cursor)
        val rec2 = Recorder()
        engine2.start(rec2)
        walk(source2, 600, 660)
        assertTrue(rec2.windows.isNotEmpty())
        assertTrue(rec2.windows.all { it > cursor })
        assertTrue(rec2.steps.last().second > 0.0)
    }
}

class WindowCountingTest {
    @Test
    fun aWindowIsCountedOnceEvenWhenTheServiceRestarts() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source, { FakeEstimator() })
        val rec = Recorder()
        engine.start(rec)
        source.onFix!!(fix(500)); source.onFix!!(fix(500)); source.onFix!!(fix(505))
        assertEquals(listOf(100L, 101L), rec.windows)
        assertEquals(14.0, rec.steps.last().second, 1e-9)
        engine.stop()
        val rec2 = Recorder()
        engine.start(rec2) // same process: cursor kept
        source.onFix!!(fix(505)); source.onFix!!(fix(510))
        assertEquals(listOf(102L), rec2.windows)
    }

    @Test
    fun persistedCursorSuppressesRecountAfterProcessDeath() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source, { FakeEstimator() })
        engine.restoreCountedWindow(101L)
        val rec = Recorder()
        engine.start(rec)
        source.onFix!!(fix(505)); source.onFix!!(fix(510))
        assertEquals(listOf(102L), rec.windows)
    }

    @Test
    fun cursorAheadOfTheClockMeansRebootAndIsCleared() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source, { FakeEstimator() })
        engine.restoreCountedWindow(5_000_000L)
        val rec = Recorder()
        engine.start(rec)
        source.onFix!!(fix(50))
        assertEquals(listOf(10L), rec.windows)
    }

    @Test
    fun excludedWindowCountsZeroAndFlagsInsufficientData() {
        val source = FakeSource()
        val engine = GpsCountingEngine(source, { FakeEstimator(raw = null) })
        val rec = Recorder()
        engine.start(rec)
        source.onFix!!(fix(15))
        assertEquals(emptyList(), rec.windows)
        assertEquals(0.0, rec.steps.last().second)
        assertEquals(listOf(true), rec.status)
    }
}