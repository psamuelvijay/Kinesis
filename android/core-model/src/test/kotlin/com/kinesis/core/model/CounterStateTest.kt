package com.kinesis.core.model

import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CounterStateTest {
    private val e = 1L

    private fun CounterState.feed(vararg values: Double, epoch: Long = e) =
        values.fold(this) { s, v -> s.onReading(epoch, v) }

    @Test fun firstReadingSetsBaselineAndShowsZero() {
        val s = CounterState().onReading(e, 5000.0)
        assertEquals(0.0, s.session)
        assertEquals(5000.0, s.baseline)
        assertEquals(5000.0, s.last)
        assertEquals(e, s.epoch)
    }

    @Test fun incrementsCount() {
        assertEquals(30.0, CounterState().feed(100.0, 110.0, 130.0).session)
    }

    @Test fun duplicateIdenticalReadingAddsNothing() {
        val s = CounterState().feed(100.0, 120.0)
        assertEquals(20.0, s.onReading(e, 120.0).session)
        assertEquals(s, s.onReading(e, 120.0))
    }

    @Test fun decreaseCarriesCommittedAndRebases() {
        val s = CounterState().feed(100.0, 150.0, 10.0)
        assertEquals(50.0, s.session)
        assertEquals(10.0, s.baseline)
        assertEquals(60.0, s.feed(20.0).session)
    }

    @Test fun epochChangeWithLargerFirstValueAddsNoPhantomSteps() {
        val s = CounterState().feed(100.0, 150.0).onReading(2L, 9000.0)
        assertEquals(50.0, s.session)
        assertEquals(55.0, s.onReading(2L, 9005.0).session)
    }

    @Test fun resetZeroesSessionKeepsLastAndCountsFromThere() {
        val s = CounterState().feed(100.0, 150.0).reset()
        assertEquals(0.0, s.session)
        assertEquals(150.0, s.last)
        assertEquals(7.0, s.feed(157.0).session)
    }

    @Test fun resetTwice() {
        val s = CounterState().feed(100.0, 150.0).reset().feed(160.0).reset()
        assertEquals(0.0, s.session)
        assertEquals(5.0, s.feed(165.0).session)
    }

    @Test fun resetClearsCommittedFromEarlierSegments() {
        val s = CounterState().feed(100.0, 150.0, 10.0).reset()
        assertEquals(0.0, s.session)
        assertEquals(4.0, s.feed(14.0).session)
    }

    @Test fun resetDuringPausedKeepsPausedAndStillExcludesGap() {
        val s = CounterState().feed(100.0, 120.0).onUserStop().reset()
        assertTrue(s.pausedByUser)
        assertEquals(0.0, s.session)
        assertEquals(3.0, s.feed(200.0, 203.0).session)
    }

    @Test fun userStopGapIsExcluded() {
        val s = CounterState().feed(100.0, 120.0).onUserStop().feed(500.0, 505.0)
        assertEquals(25.0, s.session)
    }

    @Test fun involuntaryInterruptionIncludesSteps() {
        assertEquals(420.0, CounterState().feed(100.0, 120.0, 520.0).session)
    }

    @Test fun processDeathRoundTripIsEqual() {
        val p = PersistedCounting()
            .onSteps(7L, 1234.5).onSteps(7L, 1300.0)
            .onDistance(3L, 10.25).onDistance(3L, 99.125)
            .reset(42L).onSteps(7L, 1310.0).onUserStop()
        assertEquals(p, PersistedCounting.decode(p.encode()))
        val fresh = PersistedCounting()
        assertEquals(fresh, PersistedCounting.decode(fresh.encode()))
        assertNull(PersistedCounting.decode(emptyMap()).lastResetElapsedMs)
    }

    @Test fun restoredStateContinuesWithoutDoubleCounting() {
        val p = PersistedCounting().onSteps(7L, 1000.0).onSteps(7L, 1040.0)
        val restored = PersistedCounting.decode(p.encode())
        assertEquals(40.0, restored.onSteps(7L, 1040.0).steps.session)
        assertEquals(45.0, restored.onSteps(7L, 1045.0).steps.session)
    }

    @Test fun resetOnPersistedResetsBothChannelsAndCountsResets() {
        val p = PersistedCounting().onSteps(1L, 10.0).onSteps(1L, 20.0)
            .onDistance(1L, 5.0).onDistance(1L, 15.0).reset(99L)
        assertEquals(0.0, p.steps.session)
        assertEquals(0.0, p.distanceM.session)
        assertEquals(1, p.resetCount)
        assertEquals(99L, p.lastResetElapsedMs)
        assertEquals(20.0, p.steps.last)
    }

    @Test fun invalidReadingsAreIgnored() {
        val s = CounterState().feed(100.0, 110.0)
        assertEquals(s, s.onReading(e, Double.NaN))
        assertEquals(s, s.onReading(e, Double.POSITIVE_INFINITY))
        assertEquals(s, s.onReading(e, -1.0))
        assertEquals(CounterState(), CounterState().onReading(e, Double.NaN))
    }

    @Test fun sessionNeverNegativeAndOnlyResetDecreasesIt() {
        val rnd = Random(12345)
        var s = CounterState()
        var previous = 0.0
        repeat(20_000) {
            val epoch = rnd.nextLong(1, 4)
            val value = when (rnd.nextInt(10)) {
                0 -> Double.NaN
                1 -> -rnd.nextDouble(0.0, 100.0)
                else -> rnd.nextDouble(0.0, 10_000.0)
            }
            when (rnd.nextInt(20)) {
                0 -> { s = s.reset(); previous = 0.0 }
                1 -> s = s.onUserStop()
                else -> s = s.onReading(epoch, value)
            }
            assertTrue(s.session >= 0.0, "negative session")
            assertTrue(s.session >= previous - 1e-9, "session decreased without reset: $previous -> ${s.session}")
            previous = s.session
        }
    }
}