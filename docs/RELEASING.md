# Releasing

Probo is published from a tag through `.github/workflows/release.yml`.

One-time setup (the repository owner): on pypi.org, create the `probo`
project by adding a *trusted publisher* for `cdandgey5/probo`, workflow
`release.yml`, environment `release`; then create the `release` environment
in the GitHub repository settings. No API token is stored anywhere.

Per release:

1. Update `version` in `pyproject.toml` and `__version__` in
   `src/probo/__init__.py`; move the Unreleased section of CHANGELOG.md
   under the new version with the date.
2. `uv run ruff check src tests && uv run pytest`.
3. Commit with sign-off, tag `v<version>`, push the tag. The workflow checks
   that the tag matches the package version, builds the sdist and wheel,
   publishes to PyPI, and creates the GitHub release with generated notes.

The first public release (v0.1.0) waits for the Phase 4 benchmark numbers,
per ROADMAP.md; until then the version stays `0.1.0.dev0` and no tag is
pushed.
