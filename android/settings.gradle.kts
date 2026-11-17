pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "KinesisAndroid"

include(":core-model", ":engine-gps", ":engine-physical", ":core-runtime", ":ui-shared", ":app-gps", ":app-fusion")

project(":app-gps").projectDir = file("GpsOnlyApp")
project(":app-fusion").projectDir = file("SensorFusionApp")
