package com.kinesis.engine.gps

import org.junit.Test
import java.io.File
import kotlin.math.abs
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Minimal JSON reader: objects -> Map, arrays -> List, numbers -> Double, null -> null. */
private class Json(private val s: String) {
    private var i = 0
    fun parse(): Any? = value().also { ws(); check(i == s.length) }
    private fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
    private fun value(): Any? {
        ws()
        return when (val c = s[i]) {
            '{' -> {
                i++; val m = LinkedHashMap<String, Any?>(); ws()
                if (s[i] == '}') { i++; return m }
                while (true) {
                    ws(); val k = string(); ws(); i++ // ':'
                    m[k] = value(); ws()
                    if (s[i++] == '}') return m
                }
                @Suppress("UNREACHABLE_CODE") m
            }
            '[' -> {
                i++; val l = ArrayList<Any?>(); ws()
                if (s[i] == ']') { i++; return l }
                while (true) {
                    l += value(); ws()
                    if (s[i++] == ']') return l
                }
                @Suppress("UNREACHABLE_CODE") l
            }
            '"' -> string()
            'n' -> { i += 4; null }
            't' -> { i += 4; true }
            'f' -> { i += 5; false }
            else -> {
                val st = i
                while (i < s.length && (s[i].isDigit() || s[i] in "+-.eE")) i++
                check(i > st) { "bad json at $st: $c" }
                s.substring(st, i).toDouble()
            }
        }
    }
    private fun string(): String {
        i++; val sb = StringBuilder()
        while (s[i] != '"') { if (s[i] == '\\') i++; sb.append(s[i]); i++ }
        i++
        return sb.toString()
    }
}

@Suppress("UNCHECKED_CAST")
private fun resource(name: String): Map<String, Any?> =
    Json(File("src/test/resources/$name").readText()).parse() as Map<String, Any?>

private fun doubles(list: Any?): DoubleArray =
    (list as List<Any?>).map { (it as Double?) ?: Double.NaN }.toDoubleArray()

private val model: RandomForestModel by lazy {
    RandomForestModel.parse(File("src/main/assets/gps_rf_model.bin").readBytes())
}

class GpsParityTest {

    @Test
    fun kotlinPredictionsMatchPythonOnGoldenVectors() {
        val g = resource("golden_model_vectors.json")
        assertEquals(FEATURE_ORDER, (g["feature_order"] as List<*>).map { it as String })
        assertEquals(300, model.nTrees)
        val rows = g["vectors"] as List<Map<String, Any?>>
        var maxPy = 0.0
        var maxStored = 0.0
        var nanRows = 0
        for (r in rows) {
            val f = doubles(r["features"])
            if (f.any { it.isNaN() }) nanRows++
            val p = model.predict(f)
            maxPy = maxOf(maxPy, abs(p - (r["python_prediction"] as Double)))
            maxStored = maxOf(maxStored, abs(p - (r["stored_phase2_prediction"] as Double)))
        }
        println("PARITY vectors=${rows.size} nanRows=$nanRows maxAbsDiffVsPython=$maxPy maxAbsDiffVsStoredPhase2=$maxStored")
        assertEquals(300, rows.size)
        assertTrue(nanRows >= 80)
        assertTrue(maxPy <= 1e-6, "max diff vs python $maxPy")
    }

    @Test
    fun kotlinFeaturesMatchPythonOnGoldenRawFixes() {
        val g = resource("golden_features.json")
        assertEquals(FEATURE_ORDER, (g["feature_order"] as List<*>).map { it as String })
        var maxFeat = 0.0
        var maxPred = 0.0
        var windows = 0
        for (t in g["tracks"] as List<Map<String, Any?>>) {
            val name = t["track"] as String
            val anchor = t["window_grid_start_ms"] as Double
            // Batch script C2: stable sort by ms, then drop exact duplicate rows. (Android's clock is monotonic.)
            val raw = (t["raw_fixes"] as List<Any?>).map { doubles(it) }
                .sortedBy { it[0] }.distinctBy { it.toList() }
            val fixes = raw.map {
                GpsFix(
                    (it[0] * 1e6).toLong(), it[1], it[2],
                    accuracyM = it[4].takeUnless { c -> c.isNaN() },
                    speedMps = it[3].takeUnless { s -> s.isNaN() },
                )
            }
            val nGen = (t["n_windows_generated"] as Double).toLong()
            val pipe = GpsWindowPipeline(model, anchor)
            val all = fixes.flatMap { pipe.onFix(it) } + pipe.flush()
            assertEquals(all.map { it.index }, all.map { it.index }.distinct(), "window closed twice on $name")
            // Python only generates windows up to the end of the step log (n_windows_generated).
            val got = all.filter { it.status == WindowStatus.PREDICTED && it.index < nGen }.associateBy { it.index }
            val expected = t["expected_windows"] as List<Map<String, Any?>>
            assertEquals(
                expected.map { (it["win_idx"] as Double).toLong() }.toSet(), got.keys,
                "window set differs on track $name",
            )
            for (e in expected) {
                val w = got.getValue((e["win_idx"] as Double).toLong())
                val ef = doubles(e["features"])
                for (k in ef.indices) {
                    val a = w.features!![k]
                    if (ef[k].isNaN()) {
                        assertTrue(a.isNaN(), "$name win ${e["win_idx"]} ${FEATURE_ORDER[k]} expected NaN, got $a")
                    } else {
                        assertTrue(!a.isNaN(), "$name win ${e["win_idx"]} ${FEATURE_ORDER[k]} unexpected NaN")
                        val d = abs(a - ef[k])
                        maxFeat = maxOf(maxFeat, d)
                        assertTrue(d <= 1e-6, "$name win ${e["win_idx"]} ${FEATURE_ORDER[k]}: kotlin $a python ${ef[k]}")
                    }
                }
                val dp = abs(w.rawPrediction!! - (e["rf_prediction"] as Double))
                maxPred = maxOf(maxPred, dp)
                assertTrue(dp <= 1e-6, "$name win ${e["win_idx"]} prediction diff $dp")
                assertTrue(w.steps >= 0.0)
                windows++
            }
        }
        println("PARITY features windows=$windows maxFeatureAbsDiff=$maxFeat maxPredictionAbsDiff=$maxPred")
        assertTrue(windows > 100)
    }
}
