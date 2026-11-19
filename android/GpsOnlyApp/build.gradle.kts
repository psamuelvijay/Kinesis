plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.kinesis.gpsonly"
    compileSdk = libs.versions.compileSdk.get().toInt()
    defaultConfig {
        applicationId = "com.kinesis.gpsonly"
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
    implementation(project(":engine-gps"))
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
}

// App A must never ship the physical-sensor engine: fail the build if it appears on the runtime classpath.
val verifyNoPhysicalSensorDependency by tasks.registering {
    doLast {
        val components = configurations.getByName("debugRuntimeClasspath").incoming.resolutionResult.allComponents
        val found = components.map { it.id.displayName }.filter { it.contains(":engine-physical") }
        check(found.isEmpty()) { "App A must not depend on :engine-physical, found $found" }
    }
}
tasks.named("check") { dependsOn(verifyNoPhysicalSensorDependency) }