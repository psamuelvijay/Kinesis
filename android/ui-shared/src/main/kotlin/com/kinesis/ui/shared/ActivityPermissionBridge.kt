package com.kinesis.ui.shared

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import com.kinesis.core.model.RuntimeRequirement

/**
 * [PermissionBridge] backed by an Activity. Create it in `onCreate`, before the Activity starts.
 *
 * Required permissions are requested first; POST_NOTIFICATIONS (Android 13+) is requested second
 * and never blocks counting. A permission counts as permanently denied when it was requested
 * before, is not granted, and Android no longer wants to show a rationale.
 */
class ActivityPermissionBridge(
    private val activity: ComponentActivity,
    private val onResult: () -> Unit,
) : PermissionBridge {

    private val prefs = activity.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private var notificationsPending = false

    private val launcher = activity.registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) {
        onResult()
        if (notificationsPending) {
            notificationsPending = false
            launchIfNeeded(listOf(Manifest.permission.POST_NOTIFICATIONS))
        }
    }

    override fun requestPermissions(requirements: List<RuntimeRequirement>) {
        val required = requirements.flatMap { it.permissions() }.filterNot(::isGranted)
        notificationsPending = Build.VERSION.SDK_INT >= 33 && !isGranted(Manifest.permission.POST_NOTIFICATIONS)
        if (required.isEmpty()) {
            onResult()
            if (notificationsPending) {
                notificationsPending = false
                launchIfNeeded(listOf(Manifest.permission.POST_NOTIFICATIONS))
            }
        } else {
            launchIfNeeded(required)
        }
    }

    private fun launchIfNeeded(permissions: List<String>) {
        val toAsk = permissions.filterNot(::isGranted)
        if (toAsk.isEmpty()) return
        prefs.edit { toAsk.forEach { putBoolean(it, true) } }
        launcher.launch(toAsk.toTypedArray())
    }

    override fun isPermanentlyDenied(requirement: RuntimeRequirement): Boolean {
        val missing = requirement.permissions().filterNot(::isGranted)
        if (missing.isEmpty()) return false
        return missing.all { prefs.getBoolean(it, false) && !ActivityCompat.shouldShowRequestPermissionRationale(activity, it) }
    }

    override fun openAppSettings() = open(
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", activity.packageName, null)),
    )

    override fun openLocationSettings() = open(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS))

    override fun openBatterySettings() = open(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))

    private fun open(intent: Intent) {
        try {
            activity.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            // No settings screen on this device: nothing else to offer.
        }
    }

    private fun isGranted(permission: String) =
        ContextCompat.checkSelfPermission(activity, permission) == PackageManager.PERMISSION_GRANTED

    private fun RuntimeRequirement.permissions(): List<String> = when (this) {
        // Both, so Android 12+ can show the precise/approximate choice.
        RuntimeRequirement.FINE_LOCATION ->
            listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        RuntimeRequirement.ACTIVITY_RECOGNITION -> listOf(Manifest.permission.ACTIVITY_RECOGNITION)
        RuntimeRequirement.NOTIFICATIONS_OPTIONAL ->
            if (Build.VERSION.SDK_INT >= 33) listOf(Manifest.permission.POST_NOTIFICATIONS) else emptyList()
        RuntimeRequirement.LOCATION_SERVICES -> emptyList()
    }

    private companion object {
        const val PREFS_NAME = "permission_requests"
    }
}
