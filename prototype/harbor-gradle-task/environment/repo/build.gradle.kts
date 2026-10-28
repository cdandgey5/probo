plugins {
    kotlin("jvm") version "2.2.0"
}

group = "com.example"
version = "0.1.0"

repositories {
    mavenCentral()
}

dependencies {
    testImplementation(kotlin("test"))
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

tasks.test {
    useJUnitPlatform()
    // Always produce JUnit XML under build/test-results/test; the grader parses it.
    reports.junitXml.required.set(true)
    reports.html.required.set(false)
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = false
    }
}
