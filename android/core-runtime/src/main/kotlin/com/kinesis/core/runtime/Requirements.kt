package com.kinesis.core.runtime

import com.kinesis.core.model.RequirementStatus
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.core.model.UnavailableReason

/** Result of checking an engine's [RuntimeRequirement]s against the current device state. */
data class RequirementEvaluation(
    val statuses: List<RequirementStatus>,
    /** Required (non-optional) requirements that are not met. */
    val missing: List<RuntimeRequirement>,
) {
    val canStart: Boolean get() = missing.isEmpty()

    /** The reason shown when a start is refused, or null when nothing is missing. */
    val blockReason: UnavailableReason?
        get() = when {
            missing.isEmpty() -> null
            missing.any { it != RuntimeRequirement.LOCATION_SERVICES } -> UnavailableReason.PERMISSION_DENIED
            else -> UnavailableReason.LOCATION_SERVICES_OFF
        }
}

private const val POST_NOTIFICATIONS_MIN_SDK = 33

/**
 * Pure check of [required] against [granted] runtime permissions.
 *
 * - LOCATION_SERVICES is met when [locationServicesOn] is true; it is not a permission.
 * - NOTIFICATIONS_OPTIONAL is always met below Android 13 and never blocks a start.
 */
fun evaluateRequirements(
    required: Set<RuntimeRequirement>,
    granted: Set<RuntimeRequirement>,
    sdkInt: Int,
    locationServicesOn: Boolean,
): RequirementEvaluation {
    val statuses = required.sortedBy { it.ordinal }.map { requirement ->
        val met = when (requirement) {
            RuntimeRequirement.LOCATION_SERVICES -> locationServicesOn
            RuntimeRequirement.NOTIFICATIONS_OPTIONAL ->
                sdkInt < POST_NOTIFICATIONS_MIN_SDK || requirement in granted
            else -> requirement in granted
        }
        RequirementStatus(requirement, met)
    }
    val missing = statuses
        .filter { !it.granted && it.requirement != RuntimeRequirement.NOTIFICATIONS_OPTIONAL }
        .map { it.requirement }
    return RequirementEvaluation(statuses, missing)
}
