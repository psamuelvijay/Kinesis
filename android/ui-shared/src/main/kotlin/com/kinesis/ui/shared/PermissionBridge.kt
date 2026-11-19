package com.kinesis.ui.shared

import com.kinesis.core.model.RuntimeRequirement

/** Platform actions the UI cannot perform itself. Implemented by each app's Activity. */
interface PermissionBridge {
    fun requestPermissions(requirements: List<RuntimeRequirement>)
    fun openAppSettings()
    fun openLocationSettings()
    fun openBatterySettings()
    fun isPermanentlyDenied(requirement: RuntimeRequirement): Boolean
}
