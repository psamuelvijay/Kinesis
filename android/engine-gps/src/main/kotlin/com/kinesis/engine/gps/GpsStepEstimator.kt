package com.kinesis.engine.gps

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * One location fix, free of Android types so the pipeline runs on the JVM.
 *
 * [accuracyM] is Android `Location.accuracy`, used as the equivalent of the Dryad `confInterval`
 * column that the Phase 2 model was trained on. The two are NOT guaranteed to be equivalent (different
 * receivers, different definitions of the confidence radius), so `conf_mean` and the 50 m filter
 * may behave differently on a phone than on the training data.
 */
data class GpsFix(
    val elapsedRealtimeNanos: Long,
    val latitude: Double,
    val longitude: Double,
    /** Horizontal accuracy in metres, or null when the provider reported none. */
    val accuracyM: Double?,
    /** Reported speed in m/s, or null when none was reported. */
    val speedMps: Double?,
)

/** Same radius as `hav` in ml/preprocessing/phase2_build_windows.py. */
const val EARTH_RADIUS_M = 6_371_000.0

const val MAX_ACCURACY_M = 50.0
const val TELEPORT_MPS = 10.0
const val MAX_GAP_S = 10.0
const val WINDOW_MS = 5000.0

private const val DEG_TO_RAD = Math.PI / 180.0

/** Port of Python `hav`. */
fun haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val la1 = lat1 * DEG_TO_RAD
    val la2 = lat2 * DEG_TO_RAD
    val lo1 = lon1 * DEG_TO_RAD
    val lo2 = lon2 * DEG_TO_RAD
    val s1 = sin((la2 - la1) / 2)
    val s2 = sin((lo2 - lo1) / 2)
    val a = s1 * s1 + cos(la1) * cos(la2) * s2 * s2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a.coerceIn(0.0, 1.0)))
}

// The provisional stride-based estimator (PROVISIONAL_STRIDE_M = 0.75) was removed in M2.
// App A now uses GpsWindowPipeline + RandomForestModel.
