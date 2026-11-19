package com.kinesis.ui.shared.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextAlign
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.FieldState
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RunStatus
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.ui.shared.R
import com.kinesis.ui.shared.UiTags
import com.kinesis.ui.shared.messageRes
import com.kinesis.ui.shared.theme.Spacing
import com.kinesis.ui.shared.theme.statusColors
import java.text.NumberFormat

@Composable
private fun KinesisCard(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
    ) {
        Column(Modifier.fillMaxWidth().padding(Spacing.md), verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            content()
        }
    }
}

@Composable
fun MethodBanner(profile: MethodProfile, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth().testTag(UiTags.BANNER), verticalArrangement = Arrangement.spacedBy(Spacing.xs)) {
        Text(profile.appTitle, style = MaterialTheme.typography.headlineSmall)
        Text(profile.methodName, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
        Text(
            profile.oneLineDescription,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun StepsHeroCard(stepsLabel: String, steps: Long, modifier: Modifier = Modifier) {
    KinesisCard(modifier.testTag(UiTags.STEPS_HERO)) {
        Text(stepsLabel, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            NumberFormat.getIntegerInstance().format(steps),
            style = MaterialTheme.typography.displayMedium,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.testTag(UiTags.STEPS_VALUE),
        )
        Text(
            stringResource(R.string.steps_since_reset),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun StatusCard(status: RunStatus, modifier: Modifier = Modifier) {
    val colors = MaterialTheme.statusColors
    val title: String
    val detail: String
    val icon: ImageVector
    val tint: Color
    when (status) {
        RunStatus.Counting -> {
            title = stringResource(R.string.status_counting)
            detail = stringResource(R.string.status_counting_detail)
            icon = Icons.Outlined.Check
            tint = MaterialTheme.colorScheme.primary
        }
        RunStatus.Starting -> {
            title = stringResource(R.string.status_starting)
            detail = stringResource(R.string.status_starting_detail)
            icon = Icons.Outlined.Info
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        }
        RunStatus.Stopped -> {
            title = stringResource(R.string.status_stopped)
            detail = stringResource(R.string.status_stopped_detail)
            icon = Icons.Outlined.Info
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        }
        RunStatus.Interrupted -> {
            title = stringResource(R.string.status_interrupted)
            detail = stringResource(R.string.status_interrupted_detail)
            icon = Icons.Outlined.Warning
            tint = colors.amber
        }
        is RunStatus.Blocked -> {
            title = stringResource(R.string.status_blocked, stringResource(status.reason.messageRes()))
            detail = stringResource(R.string.status_blocked_detail)
            icon = Icons.Outlined.Warning
            tint = colors.red
        }
    }
    KinesisCard(modifier.testTag(UiTags.STATUS).semantics(mergeDescendants = true) {}) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Icon(icon, contentDescription = null, tint = tint)
            Text(title, style = MaterialTheme.typography.titleMedium)
        }
        Text(detail, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** One labelled reading. The row keeps its position whatever the [FieldState] is. */
@Composable
fun <T> FieldRow(
    label: String,
    state: FieldState<T>,
    tag: String,
    modifier: Modifier = Modifier,
    formatValue: @Composable (T) -> String,
) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = Spacing.minTouch)
            .testTag(tag)
            .semantics(mergeDescendants = true) {}
            .padding(vertical = Spacing.sm),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(Spacing.sm))
        Row(
            Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Spacing.xs, Alignment.End),
        ) {
            when (state) {
                is FieldState.Value -> Text(
                    formatValue(state.value),
                    style = MaterialTheme.typography.bodyLarge,
                    textAlign = TextAlign.End,
                )
                FieldState.NotUsed -> MutedText(stringResource(R.string.field_not_used), Icons.Outlined.Info, italic = true)
                FieldState.NotEnabled -> MutedText(stringResource(R.string.field_not_enabled), Icons.Outlined.Info, italic = true)
                is FieldState.Unavailable -> MutedText(
                    stringResource(R.string.field_unavailable, stringResource(state.reason.messageRes())),
                    Icons.Outlined.Warning,
                    italic = false,
                )
                FieldState.Waiting -> Text(
                    stringResource(R.string.field_waiting),
                    style = MaterialTheme.typography.bodyMedium,
                    color = muted,
                    textAlign = TextAlign.End,
                )
            }
        }
    }
}

@Composable
private fun MutedText(text: String, icon: ImageVector, italic: Boolean) {
    Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        fontStyle = if (italic) FontStyle.Italic else FontStyle.Normal,
        textAlign = TextAlign.End,
    )
}

@Composable
fun requirementLabel(requirement: RuntimeRequirement): String = stringResource(
    when (requirement) {
        RuntimeRequirement.FINE_LOCATION -> R.string.requirement_fine_location
        RuntimeRequirement.ACTIVITY_RECOGNITION -> R.string.requirement_activity_recognition
        RuntimeRequirement.LOCATION_SERVICES -> R.string.requirement_location_services
        RuntimeRequirement.NOTIFICATIONS_OPTIONAL -> R.string.requirement_notifications
    },
)

@Composable
fun PermissionCard(
    missing: List<RuntimeRequirement>,
    permanentlyDenied: Boolean,
    onGrant: () -> Unit,
    onOpenAppSettings: () -> Unit,
    onOpenLocationSettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val locationServicesOff = RuntimeRequirement.LOCATION_SERVICES in missing
    val runtimeMissing = missing.filter { it != RuntimeRequirement.LOCATION_SERVICES }
    KinesisCard(modifier.testTag(UiTags.PERMISSION_CARD)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            Icon(Icons.Outlined.Warning, contentDescription = null, tint = MaterialTheme.statusColors.amber)
            Text(stringResource(R.string.permission_card_title), style = MaterialTheme.typography.titleMedium)
        }
        Text(stringResource(R.string.permission_card_body), style = MaterialTheme.typography.bodyMedium)
        missing.forEach { Text("\u2022 " + requirementLabel(it), style = MaterialTheme.typography.bodyMedium) }
        if (runtimeMissing.isNotEmpty()) {
            if (permanentlyDenied) {
                Text(
                    stringResource(R.string.permission_denied_permanently),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                CardButton(stringResource(R.string.permission_open_app_settings), UiTags.PERMISSION_APP_SETTINGS, onOpenAppSettings)
            } else {
                CardButton(stringResource(R.string.permission_grant), UiTags.PERMISSION_GRANT, onGrant)
            }
        }
        if (locationServicesOff) {
            CardButton(
                stringResource(R.string.permission_open_location_settings),
                UiTags.PERMISSION_LOCATION_SETTINGS,
                onOpenLocationSettings,
            )
        }
    }
}

@Composable
private fun CardButton(text: String, tag: String, onClick: () -> Unit) {
    OutlinedButton(onClick, Modifier.heightIn(min = Spacing.minTouch).testTag(tag)) { Text(text) }
}

@Composable
fun PrimaryActions(state: CountingUiState, onStart: () -> Unit, onStop: () -> Unit, onReset: () -> Unit, modifier: Modifier = Modifier) {
    val running = state.runStatus == RunStatus.Counting || state.runStatus == RunStatus.Starting
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(Spacing.sm)) {
        Button(
            onClick = if (running) onStop else onStart,
            enabled = running || state.canStart,
            modifier = Modifier.fillMaxWidth().heightIn(min = Spacing.minTouch).testTag(UiTags.ACTION_TOGGLE),
        ) {
            Text(stringResource(if (running) R.string.action_stop else R.string.action_start))
        }
        // No confirmation dialog: Reset only moves the session baseline.
        OutlinedButton(
            onClick = onReset,
            modifier = Modifier.fillMaxWidth().heightIn(min = Spacing.minTouch).testTag(UiTags.ACTION_RESET),
        ) {
            Text(stringResource(R.string.action_reset))
        }
    }
}

@Composable
fun BatteryHintCard(onOpenSettings: () -> Unit, onDismiss: () -> Unit, modifier: Modifier = Modifier) {
    KinesisCard(modifier.testTag(UiTags.BATTERY_HINT)) {
        Text(stringResource(R.string.battery_hint_title), style = MaterialTheme.typography.titleMedium)
        Text(stringResource(R.string.battery_hint_body), style = MaterialTheme.typography.bodyMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
            TextButton(onOpenSettings, Modifier.heightIn(min = Spacing.minTouch).testTag(UiTags.BATTERY_OPEN)) {
                Text(stringResource(R.string.battery_hint_open))
            }
            TextButton(onDismiss, Modifier.heightIn(min = Spacing.minTouch).testTag(UiTags.BATTERY_DISMISS)) {
                Text(stringResource(R.string.battery_hint_dismiss))
            }
        }
    }
}
