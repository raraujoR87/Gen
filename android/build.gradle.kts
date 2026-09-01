// Root build file. Plugins are declared here (with apply false) and applied
// per-module in app/build.gradle.kts. Keeping this minimal on purpose: units
// 8 and 9 add more Kotlin sources to the same :app module in parallel and
// should not need to touch this file.
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "1.9.24" apply false
}
