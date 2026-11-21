# Release evaluation: unpublished development build

The package version remains 0.1.0. No tag, package upload, hosted service or
deployment is created by this evaluation. The project uses the [MIT license](../LICENSE).
Third-party distributions retain their own licenses; upstream code/binaries/fonts
are not vendored into this package.

## Included behavior

Fourteen read-only tools cover GitHub retrieval, commit-pinned line reads, bounded
source graphs, Mermaid/text diagrams, optional static SVG and lexical walkthroughs.
The optional prepare_small_change prompt packages reuse/caller/test guidance.
Python dependency inventory reads raw pyproject.toml declarations and optional
groups with pinned manifest evidence and continuation. Two reviewed Pydantic
V1-to-V2 root-import rules flag the BaseSettings move and validator deprecation
with pinned syntax and official guidance. Other imports may be unmatched or unknown;
declarations and import matches do not establish installed versions or upgrade safety.
Focused Python import diagrams add file-grouped Mermaid and text views of a chosen
module prefix, preserving statement citations, pagination and incomplete coverage.
Module names remain unverified; this view has no SVG export or runtime-use proof.
Python import mapping adds AST statement/alias evidence, relative/wildcard target
labels and parse/acquisition coverage. It does not resolve distributions or runtime usage.
See [installation and client setup](../README.md) and the reproducible
[offline evaluation](../benchmarks/README.md).

The base install provides browsing/search, pinned reads, dependency declarations,
Python import mapping and import diagrams. The `analysis` extra adds Graphify
queries, Mermaid/text architecture views and walkthroughs; `svg` includes analysis
and adds static SVG export for architecture views. Python import diagrams remain
Mermaid/text only. The optional prompt prepares a plan; it does not apply changes.

## Verification scope

The linked offline benchmark measures retrieval and Graphify artifacts only. It
does not evaluate dependency inventory, Python import mapping or import diagrams.
Those tools and the migration import checker have separate regression and protocol
checks; the benchmark results must not be presented as measurements of the newer tools.

| Verification scope | Status |
| --- | --- |
| Windows x64, Python 3.12.13 | Local tests verified; previous installed-wheel checks recorded |
| Python MCP SDK 1.30.0 stdio client | Discovery, prompt and live pinned source flows verified |
| Other IDE/desktop clients, Linux/macOS | Unverified |
| Model answer quality, tokens and provider cost | Not measured; offline-only decision |
| Hosted CI | Disabled by maintainer policy; local checks retained |

Fresh-environment and archive checks include the packaged guide, MIT metadata,
license text and exclusion of private plans/artifacts. Native SVG is optional;
Mermaid/text remain available on failure. Python dependency auditing is not a
complete audit of native transitive code or a guarantee of security.

The latest full SVG-profile suite passed 267 tests and 10 subtests, including
10 focused migration-check cases. Lint, formatting, types and archive builds passed. A real
stdio check loaded the built wheel in an existing base-only environment and
verified five pinned synthetic pages without installing packages. This is not a
fresh-install or live GitHub check. The earlier hashed Python dependency audit
was not rerun; dependencies are unchanged. No hosted checks are claimed.

## Compatibility, migration and rollback

Existing tool identifiers/defaults remain compatible with this evaluation.
No persistent snapshot/cache/database or migration is introduced. Dependency
versions stay locked. Prompt use and SVG remain optional; client rendering varies.
Review the README when migrating from the original root script and spaced tool
names. Keep private backups of local-only documents outside release artifacts.

Before a future release, record its immutable tag/commit and archive hashes. To
roll back an installed release, reinstall a previously verified immutable wheel
and its matching locked dependencies, then restart the client/server. Revert
source changes through a PR. Never rewrite published tags or reuse a version for
different artifacts. Publishing requires a separate maintainer instruction.

## Remaining limits

Static edges do not establish runtime/deployment architecture or complete impact.
Lexical walkthroughs may rank imports/comments before implementation; verify
pinned lines. Coverage/language/acquisition budgets remain explicit. Local process
limits and Python audit hooks are not an OS sandbox. Hard host termination may
leave temporary files/workers. This build is for local single-user use; hosted
auth, multi-user isolation, retention recovery and write operations are outside it.

Broader client/platform coverage and representative real-world/model evaluation
remain unverified. A passing offline fixture is not full release-readiness proof.
