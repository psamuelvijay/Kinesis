package com.kinesis.engine.gps

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/** One location fix, free of Android types so the estimator runs on the JVM. */
data class GpsFix(
    val elapsedRealtimeNanos: Long,
    val latitude: Double,
    val longitude: Double,
    /** Horizontal accuracy in metres, or null when the provider reported none. */
    val accuracyM: Float?,
    /** Reported speed in m/s, or null when none was reported. */
    val speedMps: Float?,
)

/** Turns a stream of fixes into a cumulative step estimate. M2 swaps the implementation. */
interface StepEstimator {
    fun onFix(fix: GpsFix)
    val cumulativeSteps: Double
    val cumulativeDistanceM: Double
}

/** Mean Earth radius used for the haversine distance. */
const val EARTH_RADIUS_M = 6_371_008.8

/**
 * Stride length used to convert path distance to steps.
 *
 * Placeholder replaced by Phase 2 Model A in M2; no jitter gate; stationary GPS drift can
 * produce phantom steps.
 */
const val PROVISIONAL_STRIDE_M = 0.75

const val MAX_ACCURACY_M = 50f
const val MAX_SPEED_MPS = 10.0
const val MAX_GAP_S = 10.0

fun haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val p1 = Math.toRadians(lat1)
    val p2 = Math.toRadians(lat2)
    val dLat = p2 - p1
    val dLon = Math.toRadians(lon2 - lon1)
    val h = sin(dLat / 2) * sin(dLat / 2) + cos(p1) * cos(p2) * sin(dLon / 2) * sin(dLon / 2)
    return 2 * EARTH_RADIUS_M * asin(sqrt(h.coerceIn(0.0, 1.0)))
}

/**
 * Provisional GPS-only estimator: path distance of cleaned fixes divided by [PROVISIONAL_STRIDE_M].
 *
 * Applies only the Phase 2 cleaning rules from docs/fusion_engine_spec.md section 2:
 * invalid fixes and accuracy above [MAX_ACCURACY_M] are dropped; a fix implying more than
 * [MAX_SPEED_MPS] to both neighbours is dropped (one-fix delay buffer); gaps above [MAX_GAP_S]
 * are not bridged. Not thread-safe; feed it from one thread.
 */
class GpsStepEstimator : StepEstimator {

    private var accepted: GpsFix? = null
    private var pending: GpsFix? = null
    private var lastSeenNanos: Long? = null
    private var distanceM = 0.0

    override val cumulativeDistanceM: Double get() = distanceM
    override val cumulativeSteps: Double get() = distanceM / PROVISIONAL_STRIDE_M

    override fun onFix(fix: GpsFix) {
        if (!isValid(fix)) return
        val seen = lastSeenNanos
        if (seen != null && fix.elapsedRealtimeNanos <= seen) return // duplicate or out of order
        lastSeenNanos = fix.elapsedRealtimeNanos

        pending?.let { candidate ->
            val previous = accepted
            val teleport = previous != null && impliedSpeed(previous, candidate) > MAX_SPEED_MPS &&
                impliedSpeed(candidate, fix) > MAX_SPEED_MPS
            if (!teleport) commit(candidate)
        }
        pending = fix
    }

    private fun commit(fix: GpsFix) {
        val previous = accepted
        if (previous != null && seconds(previous, fix) <= MAX_GAP_S) distanceM += distance(previous, fix)
        accepted = fix
    }

    private fun isValid(fix: GpsFix): Boolean {
        if (!fix.latitude.isFinite() || !fix.longitude.isFinite()) return false
        if (fix.latitude !in -90.0..90.0 || fix.longitude !in -180.0..180.0) return false
        val accuracy = fix.accuracyM
        return accuracy == null || (!accuracy.isNaN() && accuracy <= MAX_ACCURACY_M)
    }

    private fun seconds(a: GpsFix, b: GpsFix) = (b.elapsedRealtimeNanos - a.elapsedRealtimeNanos) / 1e9

    private fun distance(a: GpsFix, b: GpsFix) = haversineM(a.latitude, a.longitude, b.latitude, b.longitude)

    /** Speed between two fixes; 0 across a gap longer than [MAX_GAP_S], which is never bridged anyway. */
    private fun impliedSpeed(a: GpsFix, b: GpsFix): Double {
        val dt = seconds(a, b)
        return if (dt <= 0.0 || dt > MAX_GAP_S) 0.0 else distance(a, b) / dt
    }
}
