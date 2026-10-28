A 100 percent discount should bring a price down to zero, but
`DiscountCalculator.applyDiscount(200L, 100)` returns 2.

The unit test `fullDiscountYieldsZero` in
`src/test/kotlin/com/example/pricing/DiscountCalculatorTest.kt` fails for this
reason. Fix the bug so that the whole test suite passes.

Rules:

- The project is in the current directory (`/app`) and builds with Gradle.
  Run the tests with `./gradlew test --offline` (always pass `--offline`: the
  container has no network, and every dependency is already in the local
  Gradle cache).
- Change only files under `src/main`.
- Do not edit anything under `src/test`, the Gradle build files
  (`build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`), or the
  wrapper under `gradle/`. The grader restores those files from pristine copies
  before it runs the tests and rejects any submission that touched them.
