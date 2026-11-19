package com.kinesis.core.runtime

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.kinesis.core.model.UnavailableReason
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/** Implemented by each Application so the service and controller can reach the process singleton. */
interface RuntimeProvider {
    val runtime: CountingRuntime
}

/**
 * Foreground service that keeps the engine alive while counting.
 *
 * It owns no counting state: it tells the [CountingRuntime] when it is up or gone and shows the
 * ongoing notification. START_NOT_STICKY: after a process kill it is not recreated, and the
 * runtime reports the interruption on the next launch instead.
 */
abstract class CountingService : Service() {

    /** FOREGROUND_SERVICE_TYPE_* flags passed to startForeground (0 when no type applies). */
    protected abstract val startForegroundType: Int

    private var scope: CoroutineScope? = null
    private val runtime: CountingRuntime get() = (application as RuntimeProvider).runtime

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> handleStart()
            ACTION_STOP -> {
                runtime.stop()
                stopSelf()
            }
            else -> stopSelf()
        }
        return START_NOT_STICKY
    }

    @SuppressLint("MissingPermission") // POST_NOTIFICATIONS is optional; a denied notify() is a no-op.
    private fun handleStart() {
        createChannel()
        try {
            // Must be the first action: every startForegroundService call requires it, also repeats.
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                buildNotification(runtime.state.value.sessionSteps),
                startForegroundType,
            )
        } catch (e: SecurityException) {
            fail()
            return
        } catch (e: IllegalStateException) {
            // ForegroundServiceStartNotAllowedException (API 31+) is an IllegalStateException.
            fail()
            return
        }
        if (scope != null) return // already running: a repeated start must not register anything twice
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate).also { s ->
            s.launch {
                runtime.state.map { it.sessionSteps }.distinctUntilChanged().conflate().collect { steps ->
                    notificationManager().notify(NOTIFICATION_ID, buildNotification(steps))
                    delay(NOTIFICATION_MIN_INTERVAL_MS)
                }
            }
        }
        runtime.onServiceStarted()
    }

    private fun fail() {
        runtime.onStartFailed(UnavailableReason.SERVICE_BLOCKED)
        stopSelf()
    }

    /** Android 15: a foreground service type timed out. Stop cleanly instead of being killed. */
    override fun onTimeout(startId: Int, fgsType: Int) {
        stopSelf()
    }

    override fun onDestroy() {
        scope?.cancel()
        scope = null
        runtime.onServiceStopped()
        super.onDestroy()
    }

    private fun notificationManager() = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        )
        notificationManager().createNotificationChannel(channel)
    }

    private fun buildNotification(steps: Long): Notification {
        val launch = packageManager.getLaunchIntentForPackage(packageName)
        val tap = launch?.let {
            PendingIntent.getActivity(this, 0, it, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_counting)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(getString(R.string.notification_text, steps))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            // Show at once; Android 12+ otherwise may delay a foreground-service notification by 10 s.
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(tap)
            .build()
    }

    companion object {
        const val ACTION_START = "com.kinesis.core.runtime.action.START"
        const val ACTION_STOP = "com.kinesis.core.runtime.action.STOP"
        const val CHANNEL_ID = "counting_status"
        const val NOTIFICATION_ID = 1001
        const val NOTIFICATION_MIN_INTERVAL_MS = 5_000L
    }
}
