package com.kinesis.ui.shared

import androidx.annotation.StringRes
import com.kinesis.core.model.FieldState
import com.kinesis.core.model.UnavailableReason

enum class FieldKind { VALUE, NOT_USED, NOT_ENABLED, UNAVAILABLE, WAITING }

/** Resource-free description of how a [FieldState] is shown; JVM-testable. */
data class FieldDisplay(val kind: FieldKind, val reason: UnavailableReason? = null)

fun FieldState<*>.toDisplay(): FieldDisplay = when (this) {
    is FieldState.Value -> FieldDisplay(FieldKind.VALUE)
    FieldState.NotUsed -> FieldDisplay(FieldKind.NOT_USED)
    FieldState.NotEnabled -> FieldDisplay(FieldKind.NOT_ENABLED)
    is FieldState.Unavailable -> FieldDisplay(FieldKind.UNAVAILABLE, reason)
    FieldState.Waiting -> FieldDisplay(FieldKind.WAITING)
}

@StringRes
fun UnavailableReason.messageRes(): Int = when (this) {
    UnavailableReason.SENSOR_MISSING -> R.string.reason_sensor_missing
    UnavailableReason.PERMISSION_DENIED -> R.string.reason_permission_denied
    UnavailableReason.PRECISE_LOCATION_REQUIRED -> R.string.reason_precise_location
    UnavailableReason.LOCATION_SERVICES_OFF -> R.string.reason_location_services_off
    UnavailableReason.SERVICE_BLOCKED -> R.string.reason_service_blocked
}
