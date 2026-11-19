package com.kinesis.engine.gps

import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Plain-Kotlin Random Forest regressor exported from ml/models/best_model.joblib by
 * ml/export/export_rf_for_android.py (format "KRF1", little-endian). No ML runtime dependency.
 *
 * Traversal matches scikit-learn: features are cast to float32, then `x32 <= threshold` (compared as
 * float64) goes left. NaN follows each node's missing_go_to_left flag; it is never assumed to go left.
 */
class RandomForestModel private constructor(
    private val features: Array<IntArray>,
    private val thresholds: Array<DoubleArray>,
    private val lefts: Array<IntArray>,
    private val rights: Array<IntArray>,
    private val values: Array<DoubleArray>,
    private val missingLeft: Array<BooleanArray>,
    val nFeatures: Int,
) {
    val nTrees: Int get() = features.size

    fun predict(x: DoubleArray): Double {
        require(x.size == nFeatures) { "expected $nFeatures features, got ${x.size}" }
        val x32 = FloatArray(nFeatures) { x[it].toFloat() }
        var sum = 0.0
        for (t in features.indices) {
            val f = features[t]
            val thr = thresholds[t]
            var node = 0
            while (f[node] >= 0) {
                val v = x32[f[node]]
                node = if (v.isNaN()) {
                    if (missingLeft[t][node]) lefts[t][node] else rights[t][node]
                } else if (v.toDouble() <= thr[node]) {
                    lefts[t][node]
                } else {
                    rights[t][node]
                }
            }
            sum += values[t][node]
        }
        return sum / features.size
    }

    companion object {
        fun load(stream: InputStream): RandomForestModel = parse(stream.readBytes())

        fun parse(bytes: ByteArray): RandomForestModel {
            val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val magic = ByteArray(4).also { b.get(it) }.toString(Charsets.US_ASCII)
            require(magic == "KRF1") { "bad model magic $magic" }
            require(b.int == 1) { "unsupported model version" }
            val nTrees = b.int
            val nFeatures = b.int
            val f = ArrayList<IntArray>(nTrees)
            val th = ArrayList<DoubleArray>(nTrees)
            val l = ArrayList<IntArray>(nTrees)
            val r = ArrayList<IntArray>(nTrees)
            val v = ArrayList<DoubleArray>(nTrees)
            val m = ArrayList<BooleanArray>(nTrees)
            repeat(nTrees) {
                val n = b.int
                val fa = IntArray(n); val ta = DoubleArray(n); val la = IntArray(n)
                val ra = IntArray(n); val va = DoubleArray(n); val ma = BooleanArray(n)
                for (i in 0 until n) {
                    fa[i] = b.int; ta[i] = b.double; la[i] = b.int; ra[i] = b.int
                    va[i] = b.double; ma[i] = b.get().toInt() != 0
                }
                f += fa; th += ta; l += la; r += ra; v += va; m += ma
            }
            return RandomForestModel(f.toTypedArray(), th.toTypedArray(), l.toTypedArray(), r.toTypedArray(),
                v.toTypedArray(), m.toTypedArray(), nFeatures)
        }
    }
}
