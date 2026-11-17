# Android M0 + M1 plan

Scope: M0 (shared UI scaffold) and M1 (background step counting, Reset Steps) for App A (GPS-only) and App B (sensor fusion, physical step counter only in M1). No evaluation recording, no models, no spoofing detection.

## Architecture

One Gradle build in `android/` with 7 modules. The two app modules reuse the existing directories `android/GpsOnlyApp` and `android/SensorFusionApp` through `projectDir` mapping.

| Module | Type | Contents |
|---|---|---|
| `:core-model` | Kotlin/JVM | `CounterState` reducer, `FieldState`, `MethodProfile`, `CountingUiState`, `CountingController`, `CountingEngine`, `EngineListener` |
| `:engine-gps` | Android library | `GpsStepEstimator` (provisional), `PlatformLocationSource`, `GpsCountingEngine` |
| `:engine-physical` | Android library | `StepCounterFeed`, `SensorStepCounterFeed`, `PhysicalStepsCountingEngine` |
| `:core-runtime` | Android library | DataStore `CountingStore`, `CountingRuntime`, abstract `CountingService`, notification, requirement evaluation |
| `:ui-shared` | Android library | All composables, theme, navigation, `KinesisApp(controller, permissionBridge)` |
| `:app-gps` | app `com.kinesis.gpsonly` | Manifest, `Application` container, `MainActivity`, service subclass |
| `:app-fusion` | app `com.kinesis.sensorfusion` | Same shape as `:app-gps` |

Key decisions:
- **Frontend parity by construction.** No composable exists outside `:ui-shared`. An instrumented test compares semantics tag order for both profiles.
- **App A isolation.** Gradle task `verifyNoPhysicalSensorDependency` fails if `:app-gps` depends on `:engine-physical`. App B has the mirror rule for `:engine-gps` during M1.
- **Dependency injection.** Hand-written `AppContainer` per `Application`. No Hilt/KSP.
- **No convention plugins.** Only 5 Android modules.
- **Navigation.** `navigation-compose` 2.9.8 (stable, no serialization plugin). Navigation 3 can be adopted later.
- **Theme.** Static Material 3 light/dark, no dynamic color, so both apps look the same on every device.
- **Location.** `LocationManager` `GPS_PROVIDER` at 1000 ms via `LocationManagerCompat`. No Play Services, no extra manifest merges, matches the GNSS fixes behind the Phase 2 data.

### Counting model

The UI never accumulates counts. Session count comes from a persisted reducer: `session = committed + (last - baseline)`.
- **Reset:** `baseline = last`, `committed = 0`. Never touches the sensor or stored cumulative value. Works while the service is stopped.
- **New epoch or any decrease:** `committed += last - baseline`, then `baseline = last = first new value`.
- **Epochs:** App B uses `Settings.Global.BOOT_COUNT`. App A starts a new epoch on every engine start and emits an initial 0.
- **Repeated reading:** a re-delivered identical value is a no-op (duplicate guard).
- **Stop:** user Stop excludes steps taken during the pause. Involuntary interruption includes them. (Project decision, covered by tests.)
- **Persistence:** every mutation is one atomic Preferences DataStore edit.
- **Process death:** app shows "Interrupted" with the frozen count until the user taps Start.

### Service and permissions

- `START_NOT_STICKY`, started only from a visible Activity. `startForeground` is the first action, guarded against `SecurityException` and `ForegroundServiceStartNotAllowedException`; failure publishes Blocked, no crash. Repeated start is a no-op.
- **App A:** FGS type `location`. Permissions: fine/coarse location, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`, `POST_NOTIFICATIONS`.
- **App B:** FGS type `health` (API 34+). Permissions: `ACTIVITY_RECOGNITION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_HEALTH`, `POST_NOTIFICATIONS`. No location in M1; M3 adds `health|location`.
- Neither app has `INTERNET` or `WAKE_LOCK`.
- Notification permission is requested second and does not block counting.
- Battery: dismissible hint opening `ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS`; no exemption permission.

### Engines

- **App A:** provisional estimator using Phase 2 cleaning rules (accuracy > 50 m, speed > 10 m/s to both neighbours, gap > 10 s), then haversine distance / 0.75 m placeholder stride. Label "GPS-ESTIMATED STEPS". Replaced by Model A in M2 behind a `StepEstimator` interface. Known limitation: stationary jitter yields phantom steps (no jitter gate in M1).
- **App B:** `TYPE_STEP_COUNTER`, `SENSOR_DELAY_NORMAL`, `maxReportLatency` 0, on a `HandlerThread`, registered for the whole service lifetime. Missing sensor shows "not available" and disables Start; no fallback sensors. Label "PHYSICAL STEPS" (project choice).
- **Unused fields** show "Not used by this method" (App A: sensor total, activity, movement verdict) or "Not enabled in this build" (App B fields arriving in M3). Field order is fixed: session distance, GPS speed, GPS accuracy, sensor step total since boot, activity (Model B), movement verdict.

## Conflicts between existing docs

1. **FGS type per app.** Audit §10.4 and Phase 4 §12.2 give one `health|location` list. Impossible for App A (no `ACTIVITY_RECOGNITION`). A uses `location`, B declares only what it uses.
2. **Single `MovementEngine` interface.** Audit §12.1 has `onImu`/`onStepCounter` that App A "ignores", which conflicts with "App A must not read physical sensors" and the audit's own M2 test. M1 uses separate `CountingEngine`/`EngineListener` and wires only what each app owns.
3. **Step counter in both apps.** Phase 4 §12.2 describes one service with `TYPE_STEP_COUNTER`; §12.4 and audit §10.5 say App A has none. Resolved per the user brief.
4. **Module names.** Audit §12.1 (`core-ui`, `core-engine-api`, `core-sensors`, `engine-fusion`, `app-a/b`) differs from the brief. Brief names plus `:core-runtime`; `:engine-fusion` deferred to M3.
5. **Existing directories** `android/GpsOnlyApp`, `android/SensorFusionApp`: reused via `projectDir`.
6. **Milestone numbering.** Phase 4 §12.9 has 6 milestones; audit §14 has M0 to M6 with acceptance criteria. Audit table used.
7. **Reset log event.** Phase 4 §12.3 and audit §10.5 log `reset_steps`. M1 has no recording; it stores `resetCount` and `lastResetElapsedMs` for M4. "Clear fusion state" becomes an empty `onReset()` hook.
8. **Notification permission.** Phase 4 says the notification still shows if denied; official docs say it is hidden from the drawer and visible only in Task Manager.
9. **Battery optimisation.** Audit allows `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`; Phase 4 says hint only. Hint only is used.
10. **Toolchain.** Audit §3/§14 cite AGP 8.13.2, Kotlin 2.0.21, BOM 2024.11.00, Gradle 8.13. Outdated; see `android_architecture.md`. The audit's "check Play target at M0" is answered with 36.
11. **Recording toggle and sessions list.** Audit §13 puts them in settings. Omitted from M1 (no recording); return in M4, "Not used by this method" in App A.
12. **Open audit questions.** §16 items 2 (minSdk 29) and 5 ("Not used by this method") are closed by the user. Items 3, 4, 6, 8 are not M1 matters.

## Risks and unverified areas

- No physical device attached: real step counting, screen-off counting, OEM kills, Doze, and restart behaviour on Android 14 to 17 are unverified.
- Emulator probably lacks `TYPE_STEP_COUNTER` (community reports). Check with `adb shell dumpsys sensorservice`; test App B with a fake feed and the "sensor missing" path.
- Pixel_9 AVD (API 36) boot is untested; fall back to JVM tests and report honestly.
- No API 29 image installed; API 29 covered by lint `NewApi` and SDK-gated logic only.
- If `BOOT_COUNT` is unreadable, only the decrease rule detects reboot; a reboot followed by more steps than the last saved value is miscounted (documented limitation).
- Play fine-location declaration for API 37 targets does not affect target 36.
- `results/android_m0_m1_tmp/` is untracked and not ignored: stage explicit `android/` and `docs/` paths only. `Kinesis - data` is untouched.
