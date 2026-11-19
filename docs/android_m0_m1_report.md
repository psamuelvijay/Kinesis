# Android M0 + M1 report

Branch: `android-m0-m1` (based on `logger-audit` at `96fb035`). Scope is M0 (shared UI scaffold) and M1 (background step counting and Reset Steps). M2 has not been started.

Evidence labels used below:
- **Build/JVM/emulator-verified**: run on this machine (Gradle, JVM unit tests, Pixel_9 AVD API 35).
- **adb-verified**: checked over adb on a physical phone (OPPO CPH2213, Android 13, App A only).
- **Manually verified by user**: confirmed by the user on a phone. Originally this covered only the in-app permission grants and Start taps needed for the adb checks.

**Update (user reports after the report was written; supersedes the "App B not installed" statements below):**

- **App A, Phone A (OPPO CPH2213, Android 13, serial `9DXGAUMRYDOV69L7`), manually verified by user:** walking outdoors, the GPS-estimated step count kept increasing with the screen off. The user then reported the manual checklist as "all tested and fine". No step counts, distances or accuracy values were recorded, so this shows the counting pipeline behaves correctly, not that the placeholder estimate is accurate.
- **App B, Phone B (OnePlus Nord 2T 5G, CPH2401, Android 14 / API 34, serial `UOBACMH6US6DFABY`), adb-verified:**
  - The phone has a hardware `TYPE_STEP_COUNTER` (MTK, on-change, non-wake-up, no batching).
  - `adb -s UOBACMH6US6DFABY install -r app-fusion-debug.apk` succeeded, and the app launched with no crash in the logcat crash buffer.
  - After the user granted the permissions in the app and tapped Start: `SensorFusionCountingService` was foreground (id 1001, type `health`), the notification was posted, and `ACTIVITY_RECOGNITION` and `POST_NOTIFICATIONS` were granted.
  - `SensorStepCounterFeed` (pid 9911) was registered on `STEP_COUNTER` with 0 dropped events.
  - With the screen off for 30 s, the phone reached the `Dozing` state. The same pid stayed alive and the service stayed foreground.
- **App B, Phone B, manually verified by user:** the user walked with App B and reported "counting good". No counted-versus-displayed step numbers were recorded, so physical step-count accuracy is not quantified.
- **Still unverified:** long screen-off runs under OEM battery management, reboot handling on a real phone, Android 10–12, and quantified step accuracy for both apps.

## 1. Architecture and implementation summary

One Gradle build in `android/` with 7 modules. All UI lives in one shared module. The two apps differ only in their manifest, application id, service class and the counting engine they plug in.

```
:app-gps (GpsOnlyApp)  ─┬─> :ui-shared ─> :core-model
                        ├─> :core-runtime ─> :core-model
                        └─> :engine-gps ─> :core-model
:app-fusion (SensorFusionApp) ─┬─> :ui-shared
                               ├─> :core-runtime
                               └─> :engine-physical ─> :core-model
```

- `:core-model` (pure Kotlin): the counter reducer `session = committed + (last - baseline)`, the persisted state, UI state, `FieldState`, `MethodProfile`, and the `CountingController` / `CountingEngine` / `EngineListener` interfaces.
- `:core-runtime`: Preferences DataStore persistence, `CountingRuntime` (single mutation queue, live state), an abstract foreground `CountingService`, `AndroidCountingController`, and the pure `evaluateRequirements` function for permission and sensor checks.
- `:ui-shared`: every composable (Home, Settings, About, navigation bar, cards, field rows), a static Material 3 theme, `CountingViewModel`, and the permission bridge. It takes a controller and a bridge, so it does not know which engine runs.
- `:engine-gps` (App A only): GPS-only estimator and `LocationManager` `GPS_PROVIDER` source. No sensor APIs and no Play Services.
- `:engine-physical` (App B only): `TYPE_STEP_COUNTER` feed with boot-count epoch handling.
- Gradle checks `verifyNoPhysicalSensorDependency` (App A) and `verifyNoGpsDependency` (App B) run as part of `check`.
- Neither app declares `INTERNET` or `WAKE_LOCK`. No evaluation recording, no Phase 2-4 models and no spoofing detection exist in this milestone.
- Fields a method does not use stay on screen with the state "Not used by this method" (or "Not enabled" for App B fields that belong to later phases). `ParityTest` checks that both apps render the same ordered list of UI tags.
- Terminology on screen: "Movement accepted" / "Movement flagged" style only. `BannedWordsTest` scans the string resources for disallowed terms.

Versions: minSdk 29, compile/target SDK 36, AGP 9.3.3, Gradle 9.5.0 (wrapper, sha256 pinned), Kotlin 2.4.21, Compose BOM 2026.06.01, DataStore 1.3.0. Rationale and sources: `docs/android_architecture.md`. Plan and documentation conflicts: `docs/android_m0_m1_plan.md`.

## 2. Important files

Docs: `docs/android_m0_m1_plan.md`, `docs/android_architecture.md`, `docs/android_m0_m1_report.md`.

| Area | Files |
|---|---|
| Build | `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle/libs.versions.toml`, `android/gradlew(.bat)` |
| Domain | `android/core-model/.../CounterState.kt`, `PersistedCounting.kt`, `FieldState.kt`, `MethodProfile.kt`, `CountingUiState.kt`, `Engine.kt` |
| Runtime | `android/core-runtime/.../CountingRuntime.kt`, `CountingStore.kt`, `CountingService.kt`, `AndroidCountingController.kt`, `Requirements.kt` |
| Shared UI | `android/ui-shared/.../KinesisApp.kt`, `screens/Screens.kt`, `components/Components.kt`, `theme/Theme.kt`, `CountingViewModel.kt`, `FieldDisplay.kt`, `ActivityPermissionBridge.kt`, `UiTags.kt` |
| App A engine | `android/engine-gps/.../GpsCountingEngine.kt`, `GpsStepEstimator.kt`, `PlatformLocationSource.kt` |
| App B engine | `android/engine-physical/.../PhysicalStepsCountingEngine.kt`, `StepCounterFeed.kt` |
| App A shell | `android/GpsOnlyApp/src/main/AndroidManifest.xml`, `GpsCountingService.kt`, `GpsOnlyApplication.kt`, `MainActivity.kt` |
| App B shell | `android/SensorFusionApp/src/main/AndroidManifest.xml`, `SensorFusionCountingService.kt`, `SensorFusionApplication.kt`, `MainActivity.kt` |
| Tests | JVM: `CounterStateTest`, `CountingRuntimeTest`, `GpsEngineTest`, `PhysicalEngineTest`, `FieldDisplayTest`, `BannedWordsTest`. Instrumented: `ParityTest`, `PermissionCardTest`, `MainActivitySmokeTest` (both apps), `CountingServiceTest` (both apps), `FakeFeedRuntimeTest` (App B) |

## 3. How background counting works

Common to both apps:
- `CountingService` (in `:core-runtime`) calls `startForeground` first, with a low-importance ongoing notification (id 1001, channel `counting_status`). If the system refuses, the service reports a Blocked state instead of crashing. Starting twice is idempotent.
- The service is `START_NOT_STICKY`. Android does not allow a location foreground service to be started from the background, so a killed service is not restarted by the system. After process death the app shows an Interrupted state with the count frozen at its last persisted value, and the user taps Start to continue.
- Readings from the engine go through `CountingRuntime`, which persists each change in DataStore and updates the live state. The activity only observes that state, so recreating the activity does not start a second engine or double-count.

App A (GPS only): the service has foreground service type `location`. `GpsCountingEngine` receives `GPS_PROVIDER` fixes from `LocationManager`, and `GpsStepEstimator` turns the distance between accepted fixes into steps using a 0.75 m placeholder stride. This estimator is provisional and is replaced by the Phase 2 estimator in M2. App A has no `ACTIVITY_RECOGNITION` permission and no dependency on `:engine-physical`.

App B (physical steps): the service has foreground service type `health` (Android 14+). `PhysicalStepsCountingEngine` registers for `TYPE_STEP_COUNTER`, which reports cumulative steps since boot. A boot-count epoch and counter-decrease handling carry the committed total over a reboot. If the sensor is missing the app shows an unavailable state and does not fall back to anything else. The GPS, activity and verdict fields show "Not enabled". This is not sensor fusion yet.

## 4. How Reset Steps works

- The engine's cumulative reading is never modified. Reset moves the baseline to the last reading and sets the committed total to 0, so the session count is 0 immediately and rises from the next reading.
- Reset works while counting and while stopped, and is applied through the same mutation queue as readings, so a reset and a concurrent reading cannot interleave.
- App restart / process death: baseline, committed total and last reading are in DataStore. After the app or process returns, the session count is the persisted value and the state is Interrupted until Start. Start resumes without a jump, because the new reading is compared against the persisted baseline.
- Device reboot (App B): the step counter restarts from 0. The boot-count epoch detects this and adds the pre-reboot session count to the committed total, so the session count does not drop or jump.
- `CountingRuntimeTest` covers reset while stopped, reset concurrent with readings, and reset across process death.

## 5. Build and test results

Commands were run from `android/`. `GRADLE_USER_HOME=E:\gradle-user-home` was used because drive C: was full. The pass counts below come from the commit messages of the commits that ran them.

| Check | Command | Result |
|---|---|---|
| Foundation | `gradlew test assembleDebug`, `gradlew :app-gps:lintDebug :app-fusion:lintDebug` | BUILD SUCCESSFUL, `CounterStateTest` 16/16 |
| M0 | `gradlew test assembleDebug :app-gps:lintDebug :app-fusion:lintDebug :ui-shared:connectedDebugAndroidTest :app-gps:connectedDebugAndroidTest :app-fusion:connectedDebugAndroidTest` on Pixel_9 AVD (API 35) | BUILD SUCCESSFUL, 8/8 instrumented tests |
| M1 build | `gradlew test check assembleDebug assembleDebugAndroidTest` | BUILD SUCCESSFUL. JVM tests: core-model 16, core-runtime 17, engine-gps 12, engine-physical 3, ui-shared all pass. Both `verify*` tasks pass. Lint 0 errors. |
| M1 instrumented | `gradlew test :app-gps:lintDebug :app-fusion:lintDebug connectedDebugAndroidTest` on Pixel_9 AVD (API 35) | BUILD SUCCESSFUL, 17/17 instrumented tests |

Merged debug manifests of both apps contain no `INTERNET`, and App A has no `ACTIVITY_RECOGNITION`. The final commit was independently reviewed from the diff and evidence (verdict: approved; no test suites re-run by the reviewer).

## 6. Verified and unverified

### Build/JVM/emulator-verified
- Both apps build; JVM and instrumented tests pass as listed in section 5.
- Both apps cold-launch on the emulator without a crash. Home screenshots of the two apps show the same layout, and `ParityTest` asserts identical ordered tags and field states.
- Manual App A emulator run with `adb emu geo fix`: the count rose in the foreground, after pressing HOME, and with the screen off. Reset gave 0. Force-stop led to Interrupted with a frozen count, and Start resumed without a jump. There was one foreground service record (type location) and no sensor connection from App A.
- App A does not use step sensors: no sensor dependency (Gradle check), no `android.hardware` references in `:engine-gps`, no step-sensor permission or feature in the manifest.

### adb-verified (Phone A: OPPO CPH2213, Android 13, serial `9DXGAUMRYDOV69L7`, App A only)
- `adb -s 9DXGAUMRYDOV69L7 install -r` succeeded.
- Manifest: location, foreground-service-location and notification permissions only. No `ACTIVITY_RECOGNITION`, `BODY_SENSORS` or step-sensor feature.
- Launch: `MainActivity` in the foreground, no FATAL EXCEPTION or ANR in logcat.
- After the permissions were granted in the app and Start was tapped: `GpsCountingService` showed `isForeground=true`, `foregroundId=1001`, and notification id 1001 on `counting_status` was posted and ongoing.
- The process kept the same pid (26758) from first launch through the checks.
- Screen off (keyevent 26): the phone reported Asleep. After about 33 s the same process was alive and the service was still in the foreground. This is a short check only.
- `pm grant` is rejected on this OPPO (`GRANT_RUNTIME_PERMISSIONS` SecurityException), so permissions could only be granted in the app.

### Manually verified by user
- Granting location and notification permissions in the in-app dialogs and tapping Start (needed for the adb checks above).
- Nothing else. No outdoor walk has been done.

### Unverified
- App B on any physical phone (Phone B was not connected, so the APK is not installed anywhere).
- Real step counting with `TYPE_STEP_COUNTER`; the emulator has no step counter.
- App A counting real GPS movement outdoors. The displayed number is a GPS estimate, not a physical step count.
- Screen-off counting over minutes on real hardware, Doze, and OEM background kills (ColorOS and others).
- Android API 29-33 behaviour beyond the one Android 13 phone, and API 36 (tests ran on API 35).
- Real runtime-permission denial and revocation flows, and location-off handling, on hardware.
- Whether the step-counter sensor exists on Phone A (`dumpsys sensorservice` returned nothing; it does not matter for App A).

## 7. Limitations and known issues

1. App A's estimator is a placeholder. A stale first fix and stationary drift can produce phantom steps (about 430 of 532 in the emulator run). M2 replaces it, with a stale-fix filter and an accuracy/jitter gate.
2. Permission card: the Grant button only requests permissions. The user must tap Start again after granting. This was seen on the OPPO phone (first Start looked like it did nothing). It is a usability issue, not a crash, and was left unchanged because changing it alters app behaviour.
3. `START_NOT_STICKY`: if Android or the OEM kills the service, counting stops until the user reopens the app and taps Start. The count stays frozen at the last persisted value and the state shows Interrupted.
4. The battery-hint dismissal uses `rememberSaveable`, so it reappears after process death.
5. `CountingRuntime` drops a mutation after 3 failed DataStore writes with IOException. Later readings re-derive the session total, but a lost reset or stop would not be re-derived.
6. App B's profile is called "Sensor fusion", but it only forwards the hardware step counter. Fusion is Phase 4 work.
7. Newer androidx releases that need compileSdk 37 are pinned lower because that platform is not installed.
8. ColorOS (OPPO): for longer screen-off runs set battery usage to Unrestricted or Allow background activity, enable Auto-launch, lock the app in Recents and turn off battery optimization for the app. This guidance is not verified for long runs.

## 8. Build and run commands

From `E:\My_Projects\Major Project\android` (PowerShell):

```powershell
$env:GRADLE_USER_HOME = "E:\gradle-user-home"   # optional, only if C: is short on space
.\gradlew.bat test check assembleDebug assembleDebugAndroidTest
.\gradlew.bat :app-gps:lintDebug :app-fusion:lintDebug
# Emulator tests (an AVD must be running; use -s if several devices are attached)
.\gradlew.bat connectedDebugAndroidTest
```

APK output paths (relative to `android/`):
- App A: `GpsOnlyApp\build\outputs\apk\debug\app-gps-debug.apk` (`com.kinesis.gpsonly`)
- App B: `SensorFusionApp\build\outputs\apk\debug\app-fusion-debug.apk` (`com.kinesis.sensorfusion`)

Two phones: list serials with `adb devices`, then always use `-s`.

```powershell
adb devices
# Phone A (App A)
adb -s <SERIAL_A> install -r GpsOnlyApp\build\outputs\apk\debug\app-gps-debug.apk
adb -s <SERIAL_A> shell am start -n com.kinesis.gpsonly/.MainActivity
# Phone B (App B)
adb -s <SERIAL_B> install -r SensorFusionApp\build\outputs\apk\debug\app-fusion-debug.apk
adb -s <SERIAL_B> shell am start -n com.kinesis.sensorfusion/.MainActivity
```

Phone A used here has serial `9DXGAUMRYDOV69L7`. On OPPO phones `pm grant` and `monkey` may be blocked, so grant permissions in the app. Each app needs location and notification permission. App B also needs the physical-activity permission to read the step counter.

## 9. Branch and commits

Branch `android-m0-m1`, on top of `96fb035`:

| Commit | Message |
|---|---|
| `85b6671` | docs: add Android M0/M1 plan and architecture |
| `e576544` | feat(android): add Gradle multi-module foundation and pure counting domain |
| `63e52e7` | feat(android): shared Compose UI and thin app shells (M0) |
| `f0b78a5` | feat(android): background step counting and Reset Steps (M1) |

The commit that adds this report and the preservation check is the branch head after `f0b78a5`.

## 10. Unrelated files and the logger repository

`results/metrics/android_m0_m1_preservation_check.json` holds SHA-256 hashes taken before and after the work.
- Preserved user files and directories: the 7 listed files under `docs/`, `.agents/`, `datasets/dryad/processed/phase3_modelA_sensitivity/`, `results/metrics/phase3_gates/` and `results/logger_audit_tmp/`. 1110 files, all identical before and after.
- `Kinesis - data` (the logger repository, read-only): 1093 files, identical hashes. HEAD is still `4a48317002e68995b429c84f6f326fe22213ec4e` on `main`, and its `git status` is unchanged (the same 4 deleted and 6 untracked screenshots as before).
- No other branch was touched, no history was rewritten, and M0/M1 does not depend on or copy from the logger repository.
- `results/android_m0_m1_tmp/` (notes, screenshots, logs) is untracked and not committed.

## 11. Manual device test checklist

Run on a physical phone with the app installed. None of these have been done yet.

App A (Phone A):
1. Grant permissions, tap Start, walk outdoors. The count should rise plausibly. This is a GPS estimate.
2. Put the app in the background and keep walking. The count should keep rising and the notification should stay.
3. Turn the screen off for a few minutes while walking, then wake the phone. The count should have increased.
4. Tap Reset Steps. The count should go to 0 and then rise again.
5. Swipe the app out of Recents and reopen it. Nothing should be counted twice, and the state is Interrupted until you tap Start.
6. Deny or revoke permissions in Settings. The app should show a clear message and not crash.
7. Turn location off. The app should show that location is unavailable.
8. Check that the unused fields read "Not used by this method".

App B (Phone B, after installing):
1. All of the above, except that the count comes from the hardware step counter.
2. Walk and count 50 real steps by hand. Compare with the displayed count.
3. Reboot the phone mid-session and check the count does not drop or jump (section 4).
4. On a phone without a step counter, check that an unavailable message appears and nothing else is counted.

## 12. Proposed next step (M2, not started)

M2: replace App A's provisional estimator with the Phase 2 GPS estimator behind the existing engine interface, including a stale-fix filter and an accuracy gate, and rerun the emulator and phone checks. App B work (Phase 3 activity classifier, Phase 4 consistency engine, evaluation recording) would follow in later milestones. No M2 code has been written.
