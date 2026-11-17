package com.kinesis.core.model

enum class UnavailableReason {
    SENSOR_MISSING,
    PERMISSION_DENIED,
    PRECISE_LOCATION_REQUIRED,
    LOCATION_SERVICES_OFF,
    SERVICE_BLOCKED,
}

/** What a UI field shows. Every field keeps its position in every state. */
sealed interface FieldState<out T> {
    data class Value<T>(val value: T) : FieldState<T>
    /** The method deliberately does not use this input. */
    data object NotUsed : FieldState<Nothing>
    /** The method will use this input in a later release. */
    data object NotEnabled : FieldState<Nothing>
    data class Unavailable(val reason: UnavailableReason) : FieldState<Nothing>
    /** Enabled and available, but no value yet. */
    data object Waiting : FieldState<Nothing>
}