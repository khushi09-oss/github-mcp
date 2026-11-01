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

## PR structure and review

Follow the PR template: **Why**, **What**, **How I tested**, **Review focus**,
and **Risk / rollback**. Explain the problem, approach and meaningful rejected
alternatives, verification evidence, risky locations and uncertainties, then
compatibility and rollback. Keep descriptions concise and useful without chat
context. Put relevant security/bug audit findings under Review focus.

Keep PR titles, descriptions, comments and attachments focused on the change.
Do not add assistant/model names, tool attribution, generated-by footers, agent
signatures or automated co-author credits. Apply the same rule to commit messages
and trailers. Report the actual work and verification without authorship labels.

One PR should make one logical change, ideally describable in one sentence.
Aim for roughly 400 reviewable changed lines or fewer; this is guidance, not a
reason to omit necessary tests or documentation. Identify generated lockfile
churn separately. Split mechanical refactors from behavior changes and avoid
unrelated cleanup. Use dependent PRs when a larger change needs several slices.

Read your own diff before requesting review and inspect the published PR diff
after creation. Remove debug output, stray files and unclear code; explain
non-obvious choices inline when helpful. Commits should build and pass their
relevant checks, with imperative Conventional Commit subjects around 72
characters or fewer. Keep the existing squash-merge convention.

For behavior fixes, demonstrate that the regression test fails before the fix
and passes after it; cover relevant error/empty/partial/concurrent cases.
Documentation-only changes do not need artificial behavior tests. Report hosted
CI separately from local results; never imply an unrun check passed.

Review design/correctness first, then edge cases/tests, readability, and style.
Separate blockers from `nit:` feedback and respond to every thread with a change
or evidence-based explanation. Fix misleading code/docs instead of relying only
on a reply. If discussion needs a synchronous decision, record the outcome in
the PR. Do not rewrite history during review without coordinating with reviewers.
Do not submit a formal GitHub review unless explicitly requested.

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
