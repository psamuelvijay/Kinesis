package com.kinesis.sensorfusion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.kinesis.ui.shared.KinesisApp
import com.kinesis.ui.shared.preview.NoOpPermissionBridge

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as SensorFusionApplication).container
        setContent { KinesisApp(container.controller, NoOpPermissionBridge) }
    }
}