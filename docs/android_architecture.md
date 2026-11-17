# Android architecture and chosen versions (M0 + M1)

See `android_m0_m1_plan.md` for the plan and doc conflicts.

## Architecture

Single Gradle build in `android/`, 7 modules. UI is shared; only engines and manifests differ between apps.

```
:app-gps (GpsOnlyApp)  ─┬─> :ui-shared ─> :core-model
                        ├─> :core-runtime ─> :core-model
                        └─> :engine-gps ─> :core-model

:app-fusion (SensorFusionApp) ─┬─> :ui-shared
                               ├─> :core-runtime
                               └─> :engine-physical ─> :core-model
```

- `:core-model` (pure Kotlin): reducer `session = committed + (last - baseline)`, UI state, `CountingController`, `CountingEngine`/`EngineListener`.
- `:core-runtime`: Preferences DataStore with atomic edits, `CountingRuntime`, abstract foreground `CountingService` (`START_NOT_STICKY`).
- `:ui-shared`: all composables, static Material 3 theme, navigation-compose. Takes a controller and permission bridge, so the UI is independent of any engine.
- Engines are swapped per app through a hand-written `AppContainer`. Gradle checks keep App A free of `:engine-physical`.
- Service types: App A `location`; App B `health` (API 34+). Neither app declares `INTERNET` or `WAKE_LOCK`.
- Location: `LocationManager` `GPS_PROVIDER`, no Play Services.

## Versions

| Item | Version | Source |
|---|---|---|
| minSdk | 29 | User decision |
| compileSdk / targetSdk | 36 | [Play target API requirement](https://developer.android.com/google/play/requirements/target-sdk) (API 36 required from 2026-08-31); platform android-36 installed |
| AGP | 9.3.3 | [AGP 9.3 release notes](https://developer.android.com/build/releases/agp-9-3-0-release-notes) |
| Gradle | 9.5.0 | AGP 9.3 minimum and default; wrapper bootstrapped from cached 9.3.1 |
| Kotlin | 2.4.21 | [Kotlin Gradle compatibility](https://kotlinlang.org/docs/gradle-configure-project.html) |
| Compose BOM | 2026.06.01 (Compose 1.11.4, Material 3 1.4.0) | [BOM mapping](https://developer.android.com/develop/ui/compose/bom/bom-mapping) |
| core-ktx / activity-compose | 1.18.0 / 1.13.0 | Maven metadata, AAR checks |
| Lifecycle / navigation-compose | 2.10.0 / 2.9.8 | Maven metadata, AAR checks |
| DataStore | 1.3.0 | Maven metadata, AAR checks |
| Coroutines | 1.11.0 | Maven metadata |
| JUnit / androidx.test ext / runner | 4.13.2 / 1.3.0 / 1.7.0 | Maven metadata |

Notes:
- AGP 9 has built-in Kotlin: do not apply `kotlin-android` ([migration guide](https://developer.android.com/build/migrate-to-built-in-kotlin)). The Compose compiler plugin is still applied.
- Kotlin 2.4.21's fully supported AGP ceiling is 9.3.1. AGP 9.3.3 is used because 9.3.1 has a JDK 17 lint crash and a Windows R8 file-name bug, fixed in later 9.3.x patches.
- Newest androidx releases (core-ktx 1.19+, Compose 1.12+, lifecycle 2.11, navigation 2.10) need compileSdk 37, which is not installed, so they are pinned lower. If a transitive dependency pulls a compileSdk-37 library, add a `constraints {}` pin.
- JVM target 17 built with the installed JDK 21; `jvmToolchain` is not used (no JDK 17 installed).

## Platform references

- [Foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types): `health` needs `ACTIVITY_RECOGNITION` (or `HIGH_SAMPLING_RATE_SENSORS`) on Android 14+; `location` needs location permission.
- [Background start restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start): `location` FGS cannot start from the background, hence `START_NOT_STICKY` and the Interrupted state.
- [Notification permission](https://developer.android.com/develop/ui/views/notifications/notification-permission): denial hides the notification from the drawer; the FGS still runs.
