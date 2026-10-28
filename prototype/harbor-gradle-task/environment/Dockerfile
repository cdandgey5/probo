# Pure-Kotlin JVM Gradle project with every dependency pre-fetched so grading
# can run with --offline in a container that has no network.
FROM eclipse-temurin:17-jdk

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends git python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Warm Gradle home: wrapper distribution plus dependency cache, filled at build.
ENV GRADLE_USER_HOME=/opt/gradle/warm

WORKDIR /app
COPY repo/ /app/

# The repository at its base commit: one local commit, no remote, so the agent
# has nothing to fetch and every change shows up in `git diff HEAD`.
RUN chmod +x gradlew \
 && git init -q -b main \
 && git config user.email "task@example.invalid" \
 && git config user.name "task" \
 && git add -A \
 && git commit -q -m "base"

# Pre-fetch the wrapper distribution and every compile and test-runtime
# dependency. The test run is expected to fail (one test is red at base); it is
# only there to resolve the test runtime classpath.
RUN ./gradlew --no-daemon --console=plain testClasses \
 && (./gradlew --no-daemon --console=plain test --continue || true) \
 && ./gradlew --no-daemon --console=plain clean

# Expose the pinned distribution and a read-only copy of the dependency cache.
# The grader runs this `gradle` binary directly (never the project's gradlew,
# which an agent could replace) with a fresh GRADLE_USER_HOME and
# GRADLE_RO_DEP_CACHE pointing here.
RUN set -e; \
    dist="$(dirname "$(dirname "$(find /opt/gradle/warm/wrapper/dists -type f -path '*/bin/gradle')")")"; \
    ln -s "$dist" /opt/gradle/dist; \
    mkdir -p /opt/gradle/ro-cache; \
    cp -r /opt/gradle/warm/caches/modules-2 /opt/gradle/ro-cache/; \
    find /opt/gradle/ro-cache -name '*.lock' -delete; \
    rm -f /opt/gradle/ro-cache/modules-2/gc.properties; \
    chmod -R a-w /opt/gradle/ro-cache

# Prove the grader's offline path at image build time: fresh home, read-only
# cache, no network. The test task exits non-zero (red test at base); the check
# is that it ran far enough to write JUnit XML.
RUN GRADLE_USER_HOME=/tmp/probe-home GRADLE_RO_DEP_CACHE=/opt/gradle/ro-cache \
      /opt/gradle/dist/bin/gradle --offline --no-daemon --console=plain test; \
    test -f build/test-results/test/TEST-com.example.pricing.DiscountCalculatorTest.xml \
 && rm -rf /tmp/probe-home build .gradle .kotlin
