package com.kinesis.ui.shared

import java.io.File
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class BannedWordsTest {
    private val banned = Regex("\\b(rewards?|tokens?|crypto\\w*|wallets?|earn\\w*|points?|coins?)\\b", RegexOption.IGNORE_CASE)

    private fun stringFiles(): List<File> = listOf(
        "src/main/res/values/strings.xml",
        "../GpsOnlyApp/src/main/res/values/strings.xml",
        "../SensorFusionApp/src/main/res/values/strings.xml",
    ).map { File(it) }

    @Test
    fun noBannedWordsInAnyStringResource() {
        val files = stringFiles()
        files.forEach { assertTrue(it.exists(), "missing ${it.path}") }
        val hits = files.flatMap { f -> banned.findAll(f.readText()).map { "${f.name}: ${it.value}" }.toList() }
        assertEquals(emptyList(), hits)
    }
}
