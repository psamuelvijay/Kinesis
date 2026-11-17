package com.kinesis.core.model

enum class MethodId { GPS_ONLY, SENSOR_FUSION }

/** How a method treats one input field. */
enum class FieldPolicy { USED, NOT_USED, NOT_ENABLED }

/** Everything that differs between the two apps from the UI's point of view. */
data class MethodProfile(
    val id: MethodId,
    val appTitle: String,
    val methodName: String,
    val stepsLabel: String,
    val oneLineDescription: String,
    val gpsSpeed: FieldPolicy,
    val gpsAccuracy: FieldPolicy,
    val sessionDistance: FieldPolicy,
    val sensorTotalSinceBoot: FieldPolicy,
    val activity: FieldPolicy,
    val movementVerdict: FieldPolicy,
) {
    companion object {
        val GPS_ONLY = MethodProfile(
            id = MethodId.GPS_ONLY,
            appTitle = "Kinesis A",
            methodName = "GPS-only baseline",
            stepsLabel = "GPS-ESTIMATED STEPS",
            oneLineDescription = "Estimates steps from GPS movement only. No motion sensors are read.",
            gpsSpeed = FieldPolicy.USED,
            gpsAccuracy = FieldPolicy.USED,
            sessionDistance = FieldPolicy.USED,
            sensorTotalSinceBoot = FieldPolicy.NOT_USED,
            activity = FieldPolicy.NOT_USED,
            movementVerdict = FieldPolicy.NOT_USED,
        )

        val SENSOR_FUSION = MethodProfile(
            id = MethodId.SENSOR_FUSION,
            appTitle = "Kinesis B",
            methodName = "Sensor fusion",
            stepsLabel = "PHYSICAL STEPS",
            oneLineDescription = "Counts steps with the phone's physical step counter. GPS and motion checks are not enabled yet.",
            gpsSpeed = FieldPolicy.NOT_ENABLED,
            gpsAccuracy = FieldPolicy.NOT_ENABLED,
            sessionDistance = FieldPolicy.NOT_ENABLED,
            sensorTotalSinceBoot = FieldPolicy.USED,
            activity = FieldPolicy.NOT_ENABLED,
            movementVerdict = FieldPolicy.NOT_ENABLED,
        )
    }
}