package com.kinesis.ui.shared

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.kinesis.core.model.CountingController
import com.kinesis.ui.shared.screens.AboutScreen
import com.kinesis.ui.shared.screens.HomeScreen
import com.kinesis.ui.shared.screens.SettingsScreen
import com.kinesis.ui.shared.theme.KinesisTheme

private const val ROUTE_HOME = "home"
private const val ROUTE_SETTINGS = "settings"
private const val ROUTE_ABOUT = "about"

private data class Tab(val route: String, val label: Int, val icon: ImageVector, val tag: String)

private val Tabs = listOf(
    Tab(ROUTE_HOME, R.string.nav_home, Icons.Outlined.Home, UiTags.TAB_HOME),
    Tab(ROUTE_SETTINGS, R.string.nav_settings, Icons.Outlined.Settings, UiTags.TAB_SETTINGS),
    Tab(ROUTE_ABOUT, R.string.nav_about, Icons.Outlined.Info, UiTags.TAB_ABOUT),
)

/** The whole app UI. Both apps call this with their own controller; nothing else is app specific. */
@Composable
fun KinesisApp(controller: CountingController, permissionBridge: PermissionBridge) {
    val viewModel = viewModel<CountingViewModel> { CountingViewModel(controller) }
    val state by viewModel.state.collectAsStateWithLifecycle()
    var batteryHintDismissed by rememberSaveable { mutableStateOf(false) }
    val navController = rememberNavController()
    val currentRoute = navController.currentBackStackEntryAsState().value?.destination?.route

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { viewModel.refreshAvailability() }
    DisposableEffect(permissionBridge, viewModel) {
        permissionBridge.setPermissionResultListener { viewModel.onPermissionResult() }
        onDispose { permissionBridge.setPermissionResultListener(null) }
    }

    KinesisTheme {
        Surface {
            Scaffold(
                bottomBar = {
                    NavigationBar {
                        Tabs.forEach { tab ->
                            NavigationBarItem(
                                selected = currentRoute == tab.route,
                                onClick = {
                                    navController.navigate(tab.route) {
                                        popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                                        launchSingleTop = true
                                        restoreState = true
                                    }
                                },
                                icon = { Icon(tab.icon, contentDescription = null) },
                                label = { Text(stringResource(tab.label)) },
                                modifier = Modifier.testTag(tab.tag),
                            )
                        }
                    }
                },
            ) { padding ->
                NavHost(navController, startDestination = ROUTE_HOME, modifier = Modifier.padding(padding)) {
                    composable(ROUTE_HOME) {
                        HomeScreen(
                            profile = viewModel.profile,
                            state = state,
                            bridge = permissionBridge,
                            batteryHintDismissed = batteryHintDismissed,
                            onDismissBatteryHint = { batteryHintDismissed = true },
                            onStart = { viewModel.startWithPermissions(permissionBridge) },
                            onStop = viewModel::stop,
                            onReset = viewModel::resetSteps,
                        )
                    }
                    composable(ROUTE_SETTINGS) { SettingsScreen(viewModel.profile, state, permissionBridge) }
                    composable(ROUTE_ABOUT) { AboutScreen(viewModel.profile) }
                }
            }
        }
    }
}
