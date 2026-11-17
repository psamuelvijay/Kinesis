package com.kinesis.core.model

/** Everything that must survive process death, for both counting channels. */
data class PersistedCounting(
    val steps: CounterState = CounterState(),
    val distanceM: CounterState = CounterState(),
    val monitoringRequested: Boolean = false,
    val resetCount: Int = 0,
    val lastResetElapsedMs: Long? = null,
) {
    fun onSteps(epoch: Long, cumulative: Double) = copy(steps = steps.onReading(epoch, cumulative))

    fun onDistance(epoch: Long, cumulativeM: Double) = copy(distanceM = distanceM.onReading(epoch, cumulativeM))

    /** Resets the session on both channels; the sources themselves are untouched. */
    fun reset(elapsedRealtimeMs: Long) = copy(
        steps = steps.reset(),
        distanceM = distanceM.reset(),
        resetCount = resetCount + 1,
        lastResetElapsedMs = elapsedRealtimeMs,
    )

    fun onUserStop() = copy(
        steps = steps.onUserStop(),
        distanceM = distanceM.onUserStop(),
        monitoringRequested = false,
    )

    /** Flat string form for key/value storage. Doubles round-trip exactly. */
    fun encode(): Map<String, String> = buildMap {
        putChannel("steps", steps)
        putChannel("distance", distanceM)
        put("monitoring_requested", monitoringRequested.toString())
        put("reset_count", resetCount.toString())
        lastResetElapsedMs?.let { put("last_reset_elapsed_ms", it.toString()) }
    }

    companion object {
        /** Tolerant decoder: missing or malformed values fall back to defaults. */
        fun decode(map: Map<String, String>): PersistedCounting = PersistedCounting(
            steps = map.channel("steps"),
            distanceM = map.channel("distance"),
            monitoringRequested = map["monitoring_requested"]?.toBooleanStrictOrNull() ?: false,
            resetCount = map["reset_count"]?.toIntOrNull() ?: 0,
            lastResetElapsedMs = map["last_reset_elapsed_ms"]?.toLongOrNull(),
        )

        private fun MutableMap<String, String>.putChannel(name: String, c: CounterState) {
            c.epoch?.let { put("${name}_epoch", it.toString()) }
            put("${name}_last", c.last.toString())
            put("${name}_baseline", c.baseline.toString())
            put("${name}_committed", c.committed.toString())
            put("${name}_paused", c.pausedByUser.toString())
        }

        private fun Map<String, String>.channel(name: String): CounterState {
            val epoch = this["${name}_epoch"]?.toLongOrNull() ?: return CounterState(
                committed = this["${name}_committed"]?.toDoubleOrNull() ?: 0.0,
            )
            val last = this["${name}_last"]?.toDoubleOrNull() ?: return CounterState()
            return CounterState(
                epoch = epoch,
                last = last,
                baseline = this["${name}_baseline"]?.toDoubleOrNull() ?: last,
                committed = this["${name}_committed"]?.toDoubleOrNull() ?: 0.0,
                pausedByUser = this["${name}_paused"]?.toBooleanStrictOrNull() ?: false,
            )
        }
    }
}