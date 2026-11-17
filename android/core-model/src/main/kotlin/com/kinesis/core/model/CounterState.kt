package com.kinesis.core.model

/**
 * Pure, resettable accumulator for one monotonically increasing cumulative source
 * (a step total or a distance total).
 *
 * The displayed session value is derived, never accumulated by the UI:
 * `session = committed + (last - baseline)`.
 *
 * - [epoch] identifies the counter's lifetime (for example the boot count for the
 *   hardware step counter). A different epoch means the source restarted from zero.
 * - [last] is the latest valid cumulative reading.
 * - [baseline] is the cumulative reading that corresponds to a session value of
 *   `committed`.
 * - [committed] is session progress carried over from earlier segments (a source
 *   restart or a decrease).
 * - [pausedByUser] means the user stopped counting, so the next reading re-bases
 *   instead of counting the gap.
 *
 * Reset never touches the source: it only moves [baseline] to [last].
 */
data class CounterState(
    val epoch: Long? = null,
    val last: Double = 0.0,
    val baseline: Double = 0.0,
    val committed: Double = 0.0,
    val pausedByUser: Boolean = false,
) {
    /** Session value, never negative. */
    val session: Double get() = (committed + (last - baseline)).coerceAtLeast(0.0)

    fun onReading(epoch: Long, cumulative: Double): CounterState {
        if (cumulative.isNaN() || cumulative.isInfinite() || cumulative < 0.0) return this
        val previousEpoch = this.epoch ?: return CounterState(
            epoch = epoch,
            last = cumulative,
            baseline = cumulative,
            committed = committed,
            pausedByUser = false,
        )
        return when {
            epoch != previousEpoch || cumulative < last -> CounterState(
                epoch = epoch,
                last = cumulative,
                baseline = cumulative,
                committed = committed + (last - baseline),
                pausedByUser = false,
            )
            pausedByUser -> copy(
                baseline = baseline + (cumulative - last),
                last = cumulative,
                pausedByUser = false,
            )
            else -> copy(last = cumulative)
        }
    }

    /** Zeroes the session value without changing the source or [last]. */
    fun reset(): CounterState = copy(baseline = last, committed = 0.0)

    /** Marks a deliberate stop so steps taken while stopped are excluded. */
    fun onUserStop(): CounterState = copy(pausedByUser = true)
}