package com.kinesis.ui.shared.screens

import android.content.Context
import android.content.pm.PackageManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.FieldPolicy
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.ui.shared.PermissionBridge
import com.kinesis.ui.shared.R
import com.kinesis.ui.shared.UiTags
import com.kinesis.ui.shared.components.BatteryHintCard
import com.kinesis.ui.shared.components.FieldRow
import com.kinesis.ui.shared.components.MethodBanner
import com.kinesis.ui.shared.components.PermissionCard
import com.kinesis.ui.shared.components.PrimaryActions
import com.kinesis.ui.shared.components.StatusCard
import com.kinesis.ui.shared.components.StepsHeroCard
import com.kinesis.ui.shared.components.requirementLabel
import com.kinesis.ui.shared.theme.Spacing

@Composable
private fun ScreenColumn(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Spacing.md),
        verticalArrangement = Arrangement.spacedBy(Spacing.md),
    ) { content() }
}

@Composable
fun HomeScreen(
    profile: MethodProfile,
    state: CountingUiState,
    bridge: PermissionBridge,
    batteryHintDismissed: Boolean,
    onDismissBatteryHint: () -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onReset: () -> Unit,
) {
    val missing = state.requirements.filter { !it.granted && it.requirement != RuntimeRequirement.NOTIFICATIONS_OPTIONAL }
        .map { it.requirement }
    ScreenColumn {
        MethodBanner(profile)
        StatusCard(state.runStatus)
        StepsHeroCard(state.stepsLabel, state.sessionSteps)
        if (missing.isNotEmpty()) {
            val runtimeMissing = missing.filter { it != RuntimeRequirement.LOCATION_SERVICES }
            PermissionCard(
                missing = missing,
                permanentlyDenied = runtimeMissing.any { bridge.isPermanentlyDenied(it) },
                onGrant = { bridge.requestPermissions(runtimeMissing) },
                onOpenAppSettings = bridge::openAppSettings,
                onOpenLocationSettings = bridge::openLocationSettings,
            )
        }
        Text(stringResource(R.string.live_readings), style = MaterialTheme.typography.titleMedium)
        Column {
            FieldRow(stringResource(R.string.field_session_distance), state.sessionDistanceM, UiTags.FIELD_SESSION_DISTANCE) {
                stringResource(R.string.value_distance, it)
            }
            HorizontalDivider()
            FieldRow(stringResource(R.string.field_gps_speed), state.gpsSpeedMps, UiTags.FIELD_GPS_SPEED) {
                stringResource(R.string.value_speed, it)
            }
            HorizontalDivider()
            FieldRow(stringResource(R.string.field_gps_accuracy), state.gpsAccuracyM, UiTags.FIELD_GPS_ACCURACY) {
                stringResource(R.string.value_accuracy, it)
            }
            HorizontalDivider()
            FieldRow(stringResource(R.string.field_sensor_total), state.sensorTotalSinceBoot, UiTags.FIELD_SENSOR_TOTAL) {
                java.text.NumberFormat.getIntegerInstance().format(it)
            }
            HorizontalDivider()
            FieldRow(stringResource(R.string.field_activity), state.activity, UiTags.FIELD_ACTIVITY) { it }
            HorizontalDivider()
            FieldRow(stringResource(R.string.field_movement_verdict), state.movementVerdict, UiTags.FIELD_MOVEMENT_VERDICT) { it }
        }
        PrimaryActions(state, onStart, onStop, onReset)
        if (!batteryHintDismissed) {
            BatteryHintCard(onOpenSettings = bridge::openBatterySettings, onDismiss = onDismissBatteryHint)
        }
    }
}

/** How [profile] treats the inputs behind a requirement; absent requirements show this instead. */
private fun policyFor(profile: MethodProfile, requirement: RuntimeRequirement): FieldPolicy = when (requirement) {
    RuntimeRequirement.FINE_LOCATION, RuntimeRequirement.LOCATION_SERVICES -> profile.gpsSpeed
    RuntimeRequirement.ACTIVITY_RECOGNITION -> profile.sensorTotalSinceBoot
    RuntimeRequirement.NOTIFICATIONS_OPTIONAL -> FieldPolicy.USED
}

@Composable
fun SettingsScreen(profile: MethodProfile, state: CountingUiState, bridge: PermissionBridge) {
    ScreenColumn {
        Text(stringResource(R.string.settings_permissions), style = MaterialTheme.typography.titleMedium)
        Column {
            RuntimeRequirement.entries.forEachIndexed { index, requirement ->
                if (index > 0) HorizontalDivider()
                val status = state.requirements.firstOrNull { it.requirement == requirement }
                PermissionRow(requirement, profile, status?.granted)
            }
        }
        Text(stringResource(R.string.settings_battery), style = MaterialTheme.typography.titleMedium)
        Text(stringResource(R.string.battery_hint_body), style = MaterialTheme.typography.bodyMedium)
        OutlinedButton(
            onClick = bridge::openBatterySettings,
            modifier = Modifier.heightIn(min = Spacing.minTouch).testTag(UiTags.SETTINGS_BATTERY_OPEN),
        ) { Text(stringResource(R.string.battery_hint_open)) }
        HorizontalDivider()
        Row(
            Modifier.fillMaxWidth().testTag(UiTags.SETTINGS_VERSION).semantics(mergeDescendants = true) {},
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(stringResource(R.string.settings_app_version), style = MaterialTheme.typography.bodyLarge)
            Text(appVersion(LocalContext.current) ?: stringResource(R.string.settings_version_unknown))
        }
    }
}

@Composable
private fun PermissionRow(requirement: RuntimeRequirement, profile: MethodProfile, granted: Boolean?) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = Spacing.minTouch)
            .testTag(UiTags.settingsPermission(requirement.name))
            .semantics(mergeDescendants = true) {}
            .padding(vertical = Spacing.sm),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
    ) {
        Text(requirementLabel(requirement), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        when {
            granted == true -> {
                Icon(Icons.Outlined.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                Text(stringResource(R.string.requirement_granted))
            }
            granted == false -> {
                Icon(Icons.Outlined.Warning, contentDescription = null, tint = muted)
                Text(stringResource(R.string.requirement_not_granted))
            }
            else -> {
                Icon(Icons.Outlined.Info, contentDescription = null, tint = muted)
                Text(
                    stringResource(
                        if (policyFor(profile, requirement) == FieldPolicy.NOT_ENABLED) R.string.field_not_enabled
                        else R.string.field_not_used,
                    ),
                    color = muted,
                    fontStyle = FontStyle.Italic,
                )
            }
        }
    }
}

@Composable
fun AboutScreen(profile: MethodProfile) {
    ScreenColumn {
        Text(stringResource(R.string.about_title), style = MaterialTheme.typography.headlineSmall)
        Column(
            Modifier.testTag(UiTags.ABOUT_BODY),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            Text(stringResource(R.string.about_purpose), style = MaterialTheme.typography.bodyLarge)
            Text(stringResource(R.string.about_method_title), style = MaterialTheme.typography.titleMedium)
            Text(
                stringResource(
                    if (profile.id == com.kinesis.core.model.MethodId.GPS_ONLY) R.string.about_method_gps
                    else R.string.about_method_fusion,
                ),
                style = MaterialTheme.typography.bodyLarge,
            )
            Text(stringResource(R.string.about_scope_title), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.about_scope), style = MaterialTheme.typography.bodyLarge)
        }
    }
}

@Suppress("DEPRECATION")
private fun appVersion(context: Context): String? = try {
    context.packageManager.getPackageInfo(context.packageName, 0).versionName
} catch (_: PackageManager.NameNotFoundException) {
    null
}
