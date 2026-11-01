# Contributing

## Changes and pull requests

Use a focused topic branch: feat/<topic>, fix/<topic>, docs/<topic>,
chore/<topic>, refactor/<topic>, test/<topic>, or infra/<topic>.
Never commit or push directly to main. Use Conventional Commit messages and PR
titles, for example `fix: separate search qualifiers`.

Keep changes small and reversible. Include the problem, resulting behavior,
validation results, relevant security/bug findings, and risks or rollback in the
PR description. Update user documentation when shipped behavior changes.
Do not include internal plans, session notes, private repository data, or secrets
in commits, PR descriptions, screenshots, logs, or artifacts.

## Before pushing

Inspect the staged diff and stage explicit paths. Confirm every included file is
intended for publication; ignore rules do not remove already tracked files.
Run relevant tests and available checks, and report exact results and unavailable
checks honestly. Run the unit/integration checks documented in README.md.
The CI workflow runs the locked lint, format, type, build, test, dependency-audit
and installed-wheel checks. Expected jobs are quality (ubuntu-latest) and
quality (windows-latest); confirm their names/results on GitHub before configuring
required checks. Hosted execution and branch protection are pending first delivery.
Do not remove tests or weaken validation to make a change pass.

Push only topic branches. Never force-push main or shared branches. Merge requires
maintainer authorization, resolved blocking findings, and passing required checks.
Revert merged changes through another PR rather than rewriting main history.

## Dependencies and releases

Explain why new dependencies are necessary and verify license/attribution needs.
Never commit credentials or local environment files. Release publishing and
deployment are maintainer-controlled actions. Document compatibility changes and
migrations in user-facing release notes. A project license has not yet been selected.
