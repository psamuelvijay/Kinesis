plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.kinesis.sensorfusion"
    compileSdk = libs.versions.compileSdk.get().toInt()
    defaultConfig {
        applicationId = "com.kinesis.sensorfusion"
        minSdk = libs.versions.minSdk.get().toInt()
        targetSdk = libs.versions.targetSdk.get().toInt()
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures {
        compose = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(project(":core-model"))
    implementation(project(":ui-shared"))
    implementation(project(":core-runtime"))
    implementation(project(":engine-physical"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.kotlinx.coroutines.android)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    debugImplementation(libs.androidx.compose.ui.test.manifest)

    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.kotlinx.coroutines.android)
    androidTestImplementation(project(":engine-physical"))
    androidTestImplementation(project(":core-runtime"))
}

// App B does not use GPS in M1 (re-evaluated in M3): fail the build if it appears on the runtime classpath.
val verifyNoGpsDependency by tasks.registering {
    doLast {
        val components = configurations.getByName("debugRuntimeClasspath").incoming.resolutionResult.allComponents
        val found = components.map { it.id.displayName }.filter { it.contains(":engine-gps") }
        check(found.isEmpty()) { "App B must not depend on in M1: :engine-gps, found $found" }
    }
}
tasks.named("check") { dependsOn(verifyNoGpsDependency) }