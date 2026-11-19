package com.kinesis.core.runtime

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.core.location.LocationManagerCompat
import com.kinesis.core.model.CountingController
import com.kinesis.core.model.CountingUiState
import com.kinesis.core.model.MethodProfile
import com.kinesis.core.model.RuntimeRequirement
import com.kinesis.core.model.UnavailableReason
import kotlinx.coroutines.flow.StateFlow

/** Reads the real permission and location-services state and evaluates [required] against it. */
fun androidRequirementEvaluator(context: Context, required: Set<RuntimeRequirement>): () -> RequirementEvaluation {
    val app = context.applicationContext
    return {
        fun has(permission: String) =
            ContextCompat.checkSelfPermission(app, permission) == PackageManager.PERMISSION_GRANTED
        val granted = buildSet {
            if (has(Manifest.permission.ACCESS_FINE_LOCATION)) add(RuntimeRequirement.FINE_LOCATION)
            if (has(Manifest.permission.ACTIVITY_RECOGNITION)) add(RuntimeRequirement.ACTIVITY_RECOGNITION)
            if (Build.VERSION.SDK_INT >= 33 && has(Manifest.permission.POST_NOTIFICATIONS)) {
                add(RuntimeRequirement.NOTIFICATIONS_OPTIONAL)
            }
        }
        val locationManager = app.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        evaluateRequirements(
            required = required,
            granted = granted,
            sdkInt = Build.VERSION.SDK_INT,
            locationServicesOn = LocationManagerCompat.isLocationEnabled(locationManager),
        )
    }
}

/** Connects the UI to the [CountingRuntime] and the foreground service. */
class AndroidCountingController(
    context: Context,
    private val runtime: CountingRuntime,
    private val serviceClass: Class<out CountingService>,
) : CountingController {

    private val appContext = context.applicationContext

    override val profile: MethodProfile = runtime.engine.profile
    override val state: StateFlow<CountingUiState> = runtime.state

    /** Must be called from the visible Activity (Android 12+ forbids starting from the background). */
    override fun start() {
        if (!runtime.start()) return
        val intent = Intent(appContext, serviceClass).setAction(CountingService.ACTION_START)
        try {
            ContextCompat.startForegroundService(appContext, intent)
        } catch (e: RuntimeException) {
            runtime.onStartFailed(UnavailableReason.SERVICE_BLOCKED)
        }
    }

    override fun stop() {
        runtime.stop()
        appContext.stopService(Intent(appContext, serviceClass))
    }

    override fun resetSteps() = runtime.resetSteps()

    override fun refreshAvailability() = runtime.refreshAvailability()
}
