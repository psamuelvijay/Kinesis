package com.kinesis.ui.shared

/** Stable test tags. The Home tag order is part of the frontend-parity contract. */
object UiTags {
    const val BANNER = "banner"
    const val STATUS = "status"
    const val STEPS_HERO = "steps_hero"
    const val STEPS_VALUE = "steps_value"
    const val PERMISSION_CARD = "permission_card"
    const val PERMISSION_GRANT = "permission_grant"
    const val PERMISSION_APP_SETTINGS = "permission_app_settings"
    const val PERMISSION_LOCATION_SETTINGS = "permission_location_settings"
    const val FIELD_SESSION_DISTANCE = "field_session_distance"
    const val FIELD_GPS_SPEED = "field_gps_speed"
    const val FIELD_GPS_ACCURACY = "field_gps_accuracy"
    const val FIELD_SENSOR_TOTAL = "field_sensor_total"
    const val FIELD_ACTIVITY = "field_activity"
    const val FIELD_MOVEMENT_VERDICT = "field_movement_verdict"
    const val ACTION_TOGGLE = "action_toggle"
    const val ACTION_RESET = "action_reset"
    const val BATTERY_HINT = "battery_hint"
    const val BATTERY_OPEN = "battery_open"
    const val BATTERY_DISMISS = "battery_dismiss"
    const val TAB_HOME = "tab_home"
    const val TAB_SETTINGS = "tab_settings"
    const val TAB_ABOUT = "tab_about"
    const val SETTINGS_BATTERY_OPEN = "settings_battery_open"
    const val SETTINGS_VERSION = "settings_version"
    const val ABOUT_BODY = "about_body"

    fun settingsPermission(name: String) = "settings_permission_$name"
}
