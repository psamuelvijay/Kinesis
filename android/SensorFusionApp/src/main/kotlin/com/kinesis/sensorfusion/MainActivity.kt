package com.kinesis.sensorfusion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.kinesis.ui.shared.ActivityPermissionBridge
import com.kinesis.ui.shared.KinesisApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val controller = (application as SensorFusionApplication).container.controller
        val bridge = ActivityPermissionBridge(this) { controller.refreshAvailability() }
        setContent { KinesisApp(controller, bridge) }
    }
}