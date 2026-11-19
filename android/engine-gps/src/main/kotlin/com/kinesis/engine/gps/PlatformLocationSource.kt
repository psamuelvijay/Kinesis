package com.kinesis.engine.gps

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.HandlerThread
import androidx.core.content.ContextCompat
import androidx.core.location.LocationListenerCompat
import androidx.core.location.LocationManagerCompat
import androidx.core.location.LocationRequestCompat
import com.kinesis.core.model.EngineAvailability
import com.kinesis.core.model.UnavailableReason

/** Where [GpsCountingEngine] gets fixes from. The platform implementation is [PlatformLocationSource]. */
interface GpsFixSource {
    fun availability(): EngineAvailability

    /** Starts delivery on a dedicated thread. [onProblem] reports the reason when location stops working. */
    fun start(onFix: (GpsFix) -> Unit, onProblem: (UnavailableReason) -> Unit)
    fun stop()
}

/**
 * GPS_PROVIDER updates from [LocationManager], 1 s interval, no minimum distance.
 * Deliberately no Play Services (FusedLocationProviderClient).
 */
class PlatformLocationSource(context: Context) : GpsFixSource {

    private val appContext = context.applicationContext
    private val locationManager = appContext.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private var thread: HandlerThread? = null
    private var listener: LocationListenerCompat? = null

    private fun granted(permission: String) =
        ContextCompat.checkSelfPermission(appContext, permission) == PackageManager.PERMISSION_GRANTED

    override fun availability(): EngineAvailability = when {
        granted(Manifest.permission.ACCESS_FINE_LOCATION) ->
            if (LocationManagerCompat.isLocationEnabled(locationManager)) {
                EngineAvailability.Available
            } else {
                EngineAvailability.Unavailable(UnavailableReason.LOCATION_SERVICES_OFF)
            }
        granted(Manifest.permission.ACCESS_COARSE_LOCATION) ->
            EngineAvailability.Unavailable(UnavailableReason.PRECISE_LOCATION_REQUIRED)
        else -> EngineAvailability.Unavailable(UnavailableReason.PERMISSION_DENIED)
    }

    @SuppressLint("MissingPermission") // checked in availability(); SecurityException is also handled
    @Synchronized
    override fun start(onFix: (GpsFix) -> Unit, onProblem: (UnavailableReason) -> Unit) {
        if (listener != null) return
        val unavailable = availability() as? EngineAvailability.Unavailable
        if (unavailable != null) {
            onProblem(unavailable.reason)
            return
        }
        val handlerThread = HandlerThread("kinesis-gps").also { it.start() }
        val callback = object : LocationListenerCompat {
            override fun onLocationChanged(location: Location) = onFix(location.toFix())
            override fun onProviderDisabled(provider: String) {
                if (provider == LocationManager.GPS_PROVIDER) onProblem(UnavailableReason.LOCATION_SERVICES_OFF)
            }
        }
        val request = LocationRequestCompat.Builder(UPDATE_INTERVAL_MS)
            .setMinUpdateDistanceMeters(0f)
            .setQuality(LocationRequestCompat.QUALITY_HIGH_ACCURACY)
            .build()
        try {
            LocationManagerCompat.requestLocationUpdates(
                locationManager,
                LocationManager.GPS_PROVIDER,
                request,
                callback,
                handlerThread.looper,
            )
        } catch (e: SecurityException) {
            handlerThread.quitSafely()
            onProblem(UnavailableReason.PERMISSION_DENIED)
            return
        } catch (e: IllegalArgumentException) { // no GPS provider on this device
            handlerThread.quitSafely()
            onProblem(UnavailableReason.LOCATION_SERVICES_OFF)
            return
        }
        thread = handlerThread
        listener = callback
    }

    @SuppressLint("MissingPermission") // removing updates after a revoked permission is harmless
    @Synchronized
    override fun stop() {
        listener?.let { LocationManagerCompat.removeUpdates(locationManager, it) }
        listener = null
        thread?.quitSafely()
        thread = null
    }

    private fun Location.toFix() = GpsFix(
        elapsedRealtimeNanos = elapsedRealtimeNanos,
        latitude = latitude,
        longitude = longitude,
        accuracyM = if (hasAccuracy()) accuracy else null,
        speedMps = if (hasSpeed()) speed else null,
    )

    private companion object {
        const val UPDATE_INTERVAL_MS = 1_000L
    }
}
