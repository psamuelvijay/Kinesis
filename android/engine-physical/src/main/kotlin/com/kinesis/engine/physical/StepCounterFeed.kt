package com.kinesis.engine.physical

import android.content.ContentResolver
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import android.provider.Settings

/** Source of the hardware cumulative step total (steps since boot). */
interface StepCounterFeed {
    val isAvailable: Boolean
    fun start(cb: (cumulative: Float) -> Unit)
    fun stop()
}

/**
 * TYPE_STEP_COUNTER through [SensorManager]. The listener stays registered for the whole
 * service lifetime because the sensor only counts while it is activated. No batching, so the
 * display is not delayed beyond the hardware's own reporting latency.
 */
class SensorStepCounterFeed(private val sensorManager: SensorManager) : StepCounterFeed {

    private val sensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)
    private var thread: HandlerThread? = null
    private var listener: SensorEventListener? = null

    override val isAvailable: Boolean get() = sensor != null

    @Synchronized
    override fun start(cb: (cumulative: Float) -> Unit) {
        val stepSensor = sensor ?: return
        if (listener != null) return
        val handlerThread = HandlerThread("kinesis-step-counter").also { it.start() }
        val callback = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                if (event.values.isNotEmpty()) cb(event.values[0])
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }
        val registered = sensorManager.registerListener(
            callback,
            stepSensor,
            SensorManager.SENSOR_DELAY_NORMAL,
            0,
            Handler(handlerThread.looper),
        )
        if (!registered) {
            handlerThread.quitSafely()
            return
        }
        thread = handlerThread
        listener = callback
    }

    @Synchronized
    override fun stop() {
        listener?.let { sensorManager.unregisterListener(it) }
        listener = null
        thread?.quitSafely()
        thread = null
    }
}

/**
 * Epoch of the hardware counter: it restarts from zero on every reboot, and
 * [Settings.Global.BOOT_COUNT] changes on every boot. -1 when unreadable; the reducer's
 * decrease rule then covers a reboot.
 */
class BootEpochProvider(private val contentResolver: ContentResolver) {
    fun epoch(): Long = Settings.Global.getInt(contentResolver, Settings.Global.BOOT_COUNT, -1).toLong()
}
