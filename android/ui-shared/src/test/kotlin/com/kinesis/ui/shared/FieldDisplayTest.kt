package com.kinesis.ui.shared

import com.kinesis.core.model.FieldState
import com.kinesis.core.model.UnavailableReason
import org.junit.Test
import kotlin.test.assertEquals

class FieldDisplayTest {
    @Test
    fun everyFieldStateMapsToItsOwnKind() {
        assertEquals(FieldDisplay(FieldKind.VALUE), FieldState.Value(3).toDisplay())
        assertEquals(FieldDisplay(FieldKind.NOT_USED), FieldState.NotUsed.toDisplay())
        assertEquals(FieldDisplay(FieldKind.NOT_ENABLED), FieldState.NotEnabled.toDisplay())
        assertEquals(FieldDisplay(FieldKind.WAITING), FieldState.Waiting.toDisplay())
        assertEquals(
            FieldDisplay(FieldKind.UNAVAILABLE, UnavailableReason.SENSOR_MISSING),
            FieldState.Unavailable(UnavailableReason.SENSOR_MISSING).toDisplay(),
        )
    }
}
