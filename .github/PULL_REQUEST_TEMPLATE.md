## What

## Why

## Checks

- [ ] Every commit is signed off (`git commit -s`, Developer Certificate of Origin)
- [ ] `uv run ruff check src tests` and `uv run pytest` pass
- [ ] A grader change comes with a regression test or a self-test scenario
- [ ] A task change passed `probo validate-task`, and the gate where Docker was available
