package com.kinesis.engine.gps

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.sqrt

/** Feature order of ml/models/feature_list.json; the model asset was exported with this order. */
val FEATURE_ORDER = listOf(
    "n_fixes", "n_speed_valid", "displacement_m", "path_m", "speed_mean", "speed_median", "speed_max",
    "speed_std", "speed_delta", "conf_mean", "coverage_frac", "covered_dur_s", "derived_speed_mps",
    "lag_speed_mean", "lag_path_m",
)

/**
 * Index of the 5 s window containing [ms] on the grid starting at [anchorMs]. With the default anchor 0 the
 * grid is aligned to the elapsedRealtime clock, so an index means the same wall interval after a service restart.
 */
fun windowIndexOf(ms: Double, anchorMs: Double = 0.0): Long = Math.floor((ms - anchorMs) / WINDOW_MS).toLong()

enum class WindowStatus { PREDICTED, LONG_GAP_OVERLAP, NO_FIX, NO_VALID_SPEED }

/** One closed 5 s window. [steps] is 0 unless [status] is PREDICTED; [features] is null then too. */
data class WindowResult(
    val index: Long,
    val startMs: Double,
    val status: WindowStatus,
    val features: DoubleArray?,
    val rawPrediction: Double?,
    val steps: Double,
    /** Haversine length of kept-fix links ending in this window, links longer than [MAX_GAP_S] excluded. */
    val distanceM: Double,
)

/**
 * Streaming port of ml/preprocessing/phase2_build_windows.py for one session.
 *
 * Cleaning (same order as Python): non-finite position dropped (C1); a fix not newer than the
 * previous one is dropped (Python sorts and drops exact duplicates; a live stream cannot reorder);
 * accuracy null/NaN/<0/>[MAX_ACCURACY_M] dropped (C3); iterative teleport drop (C4, exact port of
 * `teleport_drop`) over a buffer of recent kept fixes. Speed is valid only if finite and >= 0;
 * hasSpeed=false arrives as null and is invalid. Invalid speeds are never replaced.
 *
 * Windows are [anchor + k*5000, anchor + (k+1)*5000) ms on the location clock (elapsedRealtimeNanos).
 * The anchor is the first accepted fix unless given. Window k is closed once [CLOSE_LOOKAHEAD] kept
 * fixes at or after its end exist, so the teleport decision and the gap spanning its end are known.
 * Each index is closed exactly once, in increasing order. Windows overlapping a gap > [MAX_GAP_S],
 * with no fix, or with no valid speed get no prediction and 0 steps. No interpolation anywhere.
 *
 * Not thread-safe; feed it from one thread.
 */
/** Turns fixes into closed windows; [GpsWindowPipeline] is the Phase 2 implementation. */
interface WindowEstimator {
    fun onFix(fix: GpsFix): List<WindowResult>
}

class GpsWindowPipeline(
    private val model: RandomForestModel,
    private var anchorMs: Double? = null,
) : WindowEstimator {
    private class P(val ms: Double, val lat: Double, val lon: Double, val speed: Double?, val conf: Double) {
        val speedOk: Boolean get() = speed != null && speed.isFinite() && speed >= 0.0
    }

    private val buffer = ArrayList<P>()
    private var lastSeenMs: Double? = null
    private var nextIndex = 0L
    private var started = false
    private var prevKeptIndex: Long? = null
    private var prevSpeedMean = Double.NaN
    private var prevPath = Double.NaN

    /** Feeds one fix; returns the windows this fix closed (possibly none). */
    override fun onFix(fix: GpsFix): List<WindowResult> {
        val ms = fix.elapsedRealtimeNanos / 1e6
        return onFixMs(ms, fix.latitude, fix.longitude, fix.speedMps, fix.accuracyM)
    }

    fun onFixMs(ms: Double, lat: Double, lon: Double, speed: Double?, accuracy: Double?): List<WindowResult> {
        if (!ms.isFinite() || !lat.isFinite() || !lon.isFinite()) return emptyList()
        val seen = lastSeenMs
        if (seen != null && ms <= seen) return emptyList()
        lastSeenMs = ms
        if (accuracy == null || accuracy.isNaN() || accuracy < 0.0 || accuracy > MAX_ACCURACY_M) return emptyList()
        if (anchorMs == null) anchorMs = ms
        if (!started) { // start at the first fix's window; never walk the grid from index 0 of a long-running clock
            started = true
            nextIndex = maxOf(0L, windowIndexOf(ms, anchorMs!!))
        }
        buffer += P(ms, lat, lon, speed, accuracy)
        return close(flush = false)
    }

    /** Closes every remaining window that starts at or before the last fix (end of a replay). */
    fun flush(): List<WindowResult> = close(flush = true)

    private fun windowStart(k: Long) = anchorMs!! + k * WINDOW_MS

    private fun close(flush: Boolean): List<WindowResult> {
        if (anchorMs == null) return emptyList()
        if (buffer.isEmpty()) return emptyList()
        val out = ArrayList<WindowResult>()
        var cleaned: List<P>? = null
        while (true) {
            val a = windowStart(nextIndex)
            val b = windowStart(nextIndex + 1)
            val ready = if (flush) buffer.last().ms >= a else buffer.count { it.ms >= b } >= CLOSE_LOOKAHEAD
            if (!ready) break
            val kept = cleaned ?: teleportDrop(buffer).also { cleaned = it }
            out += evaluate(nextIndex, a, b, kept)
            nextIndex++
        }
        if (out.isNotEmpty()) trim()
        return out
    }

    private fun trim() {
        val keepFrom = windowStart(nextIndex) - BUFFER_HISTORY_MS
        while (buffer.size > 2 && buffer[1].ms < keepFrom) buffer.removeAt(0)
    }

    private fun evaluate(k: Long, a: Double, b: Double, p: List<P>): WindowResult {
        var distance = 0.0
        var gap = false
        for (i in 1 until p.size) {
            val g0 = p[i - 1].ms
            val g1 = p[i].ms
            val dt = (g1 - g0) / 1000.0
            if (dt > MAX_GAP_S) {
                if (g0 < b && g1 > a) gap = true
            } else if (g1 >= a && g1 < b) {
                distance += haversineM(p[i - 1].lat, p[i - 1].lon, p[i].lat, p[i].lon)
            }
        }
        fun skip(status: WindowStatus) = WindowResult(k, a, status, null, null, 0.0, distance)
        if (gap) return skip(WindowStatus.LONG_GAP_OVERLAP)
        val w = p.filter { it.ms >= a && it.ms < b }
        if (w.isEmpty()) return skip(WindowStatus.NO_FIX)
        val v = w.filter { it.speedOk }.map { it.speed!! }
        if (v.isEmpty()) return skip(WindowStatus.NO_VALID_SPEED)

        val one = w.size < 2
        var pathSum = 0.0
        for (i in 1 until w.size) pathSum += haversineM(w[i - 1].lat, w[i - 1].lon, w[i].lat, w[i].lon)
        val path = if (one) Double.NaN else pathSum
        val disp = if (one) Double.NaN else haversineM(w.first().lat, w.first().lon, w.last().lat, w.last().lon)
        val covered = (w.last().ms - w.first().ms) / 1000.0
        val mean = v.sum() / v.size
        val sorted = v.sorted()
        val median = if (sorted.size % 2 == 1) sorted[sorted.size / 2]
        else (sorted[sorted.size / 2 - 1] + sorted[sorted.size / 2]) / 2.0
        val std = sqrt(v.sumOf { val d = abs(it - mean); d * d } / v.size) // numpy std, ddof=0
        val lagOk = prevKeptIndex == k - 1
        val features = doubleArrayOf(
            w.size.toDouble(),
            v.size.toDouble(),
            disp,
            path,
            mean,
            median,
            v.max(),
            std,
            v.last() - v.first(),
            w.sumOf { it.conf } / w.size,
            covered / (WINDOW_MS / 1000.0),
            covered,
            if (!one && covered > 0) path / covered else Double.NaN,
            if (lagOk) prevSpeedMean else Double.NaN,
            if (lagOk) prevPath else Double.NaN,
        )
        prevKeptIndex = k
        prevSpeedMean = mean
        prevPath = path
        val raw = model.predict(features)
        return WindowResult(k, a, WindowStatus.PREDICTED, features, raw, raw.coerceAtLeast(0.0), distance)
    }

    private fun teleportDrop(src: List<P>): List<P> {
        val p = ArrayList(src)
        while (p.size > 2) {
            val n = p.size
            val v = DoubleArray(n - 1) { i ->
                haversineM(p[i].lat, p[i].lon, p[i + 1].lat, p[i + 1].lon) /
                    max((p[i + 1].ms - p[i].ms) / 1000.0, 1.0)
            }
            var worst = -1
            var worstScore = -1.0
            for (i in 0 until n) {
                val prevBad = i > 0 && v[i - 1] > TELEPORT_MPS
                val nextBad = i < n - 1 && v[i] > TELEPORT_MPS
                val left = i == 0 || prevBad
                val right = i == n - 1 || nextBad
                if (!(left && right && (prevBad || nextBad))) continue
                val score = (if (i > 0) v[i - 1] else 0.0) + (if (i < n - 1) v[i] else 0.0)
                if (score > worstScore) { worstScore = score; worst = i }
            }
            if (worst < 0) break
            p.removeAt(worst)
        }
        return p
    }

    companion object {
        /**
         * Production pipeline: window index = floor(elapsedRealtimeMs / 5 s), so indices keep their meaning across
         * service restarts and match the persisted counted-window cursor.
         */
        fun clockAligned(model: RandomForestModel) = GpsWindowPipeline(model, anchorMs = 0.0)

        /** Kept fixes required at or after a window's end before it is closed. */
        const val CLOSE_LOOKAHEAD = 2
        /** Kept-fix history retained before the next open window for teleport and gap checks. */
        const val BUFFER_HISTORY_MS = 60_000.0
    }
}
