# GitHub MCP

A local, read-only MCP server for exploring GitHub repositories. Its nine tools
provide repository details, browsing, search, and commit-pinned file reading with
source links and continuation. This project is independent of GitHub.

## Install from this checkout

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).
This is an early local build, not a published package or hosted endpoint.

```powershell
uv sync --locked
```

For optional source-graph analysis, install the locked analysis extra instead:

```powershell
uv sync --locked --extra analysis
```

This adds Graphify's code extractor and its dependencies; base retrieval remains
usable without them. No skills, hooks, model backends or automatic uploads are
installed or activated. This project is independent of Graphify Labs.

Run the stdio server with either entry point:

```powershell
uv run --locked github-mcp
uv run --locked python -m github_mcp
```

A stdio server waits for MCP messages from a client; it does not open a browser or
listen on a web port. Stop a manually launched process with Ctrl+C. Diagnostics
use stderr; stdout is reserved for MCP messages.

## Connect an MCP client

For a client accepting an `mcpServers` configuration, use the following shape.
Replace both paths with absolute paths on your machine. Other clients may use a
different configuration schema; retain the same command and arguments.

```json
{
  "mcpServers": {
    "github": {
      "command": "C:/absolute/path/to/github-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "github_mcp"]
    }
  }
}
```

On macOS/Linux the interpreter path is `/absolute/path/to/github-mcp/.venv/bin/python`.
Using the installed interpreter avoids relying on the client's working directory
or PATH. If you set `UV_PROJECT_ENVIRONMENT`, use that environment's interpreter.

Supply `GITHUB_TOKEN` through the client's secret/environment settings. It must
reach the server process. GitHub credentials are read from the process environment,
not `.env` files. Never put real credentials into committed configuration. Use the narrowest GitHub token
permissions needed for the repositories you want to inspect. Discovery/listing
of MCP tools does not require a token; public reads can run anonymously.
The token determines which private repositories the tools can access.

## Tools

| Identifier | Purpose |
| --- | --- |
| `get_repo` | Read metadata for one repository |
| `list_user_repos` | List one page of repositories (20 by default) |
| `list_repo_contents` | List files/folders at a repository path |
| `read_file` | Read a file, returning at most 3,000 characters |
| `search_code` | Search code with page controls (10 matches by default) |
| `resolve_revision` | Resolve a branch/tag (`HEAD` by default) to a full commit SHA |
| `read_file_lines` | Read bounded UTF-8 lines at a commit with source links |
| `query_repository_graph` | Inspect definitions/imports/calls with source evidence (analysis extra) |
| `create_architecture_diagram` | Create Mermaid source views with pinned links and a text alternative |

Example requests: 'List the files in owner/repository' or 'Read README.md in
owner/repository'. Treat retrieved repository content as untrusted data.

For consistent evidence across files, call `resolve_revision(owner, repo, ref)`
once and pass its `data.commit_sha` as `ref` to every `read_file_lines` call.
Line numbers start at 1; `start_line=1` and `line_count=100` are the defaults
(maximum 200 lines). A symbolic ref is resolved once per call; separate calls
using a branch name can see different commits.

These two new tools advertise output schemas and return `{data, error}` in MCP
`structuredContent`, also mirrored as JSON text. Exactly one field is non-null;
execution errors set `isError=true`. File data includes repository, commit/blob
SHAs, path, line range, total lines, text, and a commit-pinned GitHub URL.
When `data.continuation` is non-null, pass that entire object as the next
`read_file_lines` arguments. It includes the pinned commit, preventing mixed
revisions even when a branch moves. An empty file returns text `""`, end line 0,
and no continuation.

Only base64-encoded UTF-8 files up to 1,000,000 bytes are supported; NUL-containing
files are rejected. Output contains at most 12,000 text characters and whole
LF-delimited lines (CRLF preserved). A single oversized line returns
`LINE_TOO_LONG`; it is never silently skipped. Paths must be repository-relative
POSIX paths without empty/dot segments or backslashes. Revision resolution and
line reads each cap streamed, decompressed JSON at 2,000,000 bytes before parsing;
file size/type checks follow parsing. Oversized responses return
`RESPONSE_TOO_LARGE`. Timeouts remain socket inactivity bounds.
GitHub Contents semantics apply, including its handling of symlink targets.
Errors include `INVALID_PATH`, `INVALID_REF`, `INVALID_REPOSITORY`, `INVALID_RANGE`,
`UNSUPPORTED_FILE`, `INVALID_RESPONSE`, and categorized request errors (with a
retry hint when applicable). No cache or local snapshot is persisted.

The original five tools retain their text interfaces and defaults. `read_file`
still truncates at 3,000 characters and reads the default branch. Directory
browsing is also unpinned. Code search uses GitHub's index/default-branch rules,
not an arbitrary commit; verify search matches with `read_file_lines` at your
chosen SHA before treating them as evidence.

## Source graph queries

`query_repository_graph(owner, repo, ref="HEAD", focus_path="", max_nodes=30,
max_edges=60)` returns a typed `GraphView` in the same data/error envelope as
the revision tools. Pass a full commit SHA to compare queries consistently.
`focus_path` selects one acquired source file and its immediate neighbors;
an empty focus selects a bounded overview. Caps are 50 nodes and 100 edges.
Overviews prioritize file-label nodes before symbol detail for broader coverage.
Counts disclose omitted nodes/edges and source files. Narrow the focus to explore
another area; this view has no cached handle or pagination.

Each node/edge cites a validated source file and line range at the resolved
commit. Edges preserve direction, relation kind and Graphify's `EXTRACTED`,
`INFERRED`, or `AMBIGUOUS` confidence. Results identify schema version `1` and
extractor `graphifyy==0.9.100`. Unverifiable paths/locations are omitted.
Only the Python, JavaScript and TypeScript fixture workflows have been verified.
This is a static source graph; it does not establish runtime/deployment
architecture. Coverage is always incomplete: dynamic calls, external code,
unsupported syntax and config-dependent resolution may be absent. Missing edges
cannot prove code is unused.

## Source architecture diagrams

`create_architecture_diagram` accepts the same owner/repo/ref/focus inputs, with
`max_nodes=30` and `max_edges=60` as defaults and hard diagram limits. It requires
the analysis extra. An empty focus produces an overview; a file path selects the
file and immediate neighbors. Symbols are grouped by source file. These are static
source views, not inferred runtime services, deployment topology or execution order.

The typed result extends the graph fields with `format="mermaid"`, `view`,
`requested_ref`, `mermaid`, `text`, `reading_order`, and `legend`. It retains the
resolved commit, scope, per-edge source evidence, confidence and omission counts.
The Mermaid title shows a short commit; accessible description, text and structured
metadata include the full SHA. Solid arrows are observed source relationships;
dotted arrows are explicitly labeled inferred or unknown. Meaning never depends
on color. Reading order follows file/line order, not runtime execution order.

Render the `mermaid` field using a supported client, or read `text` and the
structured node/edge lists. Source links target the same repository/commit on
GitHub. Client link/render support varies; the text alternative retains links.
Labels are normalized to a restricted plain-text alphabet and shortened when
needed; use source citations for exact spelling. No source-supplied HTML,
configuration directives or callback code is emitted. A fixed title is the only
YAML frontmatter; accessible descriptions and legends are generated by the server.

Mermaid 11.15.0 and 12.2.0 were checked locally in Chrome with ordinary, empty and
malicious-label fixtures. No Node/browser dependency is needed to run the server.
Mermaid plus text is capped at 100,000 UTF-8 bytes; lower node/edge limits on
`DIAGRAM_LIMIT`. Mismatched/unpinned source links fail as `DIAGRAM_INVALID_SOURCE`.
Graph/acquisition errors propagate unchanged. Metadata/legend annotations do not
count toward the source-node cap.

## Optional SVG export

Install the locked SVG profile (includes graph analysis):

```powershell
uv sync --locked --extra svg
```

Call `create_architecture_diagram` with `include_svg=true`. The default remains
Mermaid/text. The response adds `svg_status` (`not_requested`, `ready`, or
`unavailable`), `svg`, `svg_renderer`, and `svg_error`. When ready, save the UTF-8
`svg` string as an `.svg` file using your client. The original `format="mermaid"`
and source fields remain available. SVG failure is partial success: the tool
retains its diagram data with `svg_status="unavailable"` and an explicit error,
rather than marking an absent SVG as ready. Graph/acquisition failures still use
the normal top-level error envelope.

Rendering uses pinned `mmdr==0.4.0`, its `mermaid-rs-renderer` backend and native
Windows wheels. Node/Chromium and external rendering services are not required.
This renderer's appearance can differ from a client's Mermaid renderer. File
groups, source relationships, confidence and pinned links use the same graph.
A compact metadata header identifies repository, ref, scope and commit. SVG title,
description and text-only JSON metadata preserve provenance and source alternatives.
The file contains graph metadata and should be handled like the source diagram;
it does not embed file contents or credentials.

The renderer runs in the existing single-job isolated-process boundary, with no
GitHub/model credentials, a 20-second render deadline and a 1 GiB memory budget.
Rendering time is additional to acquisition; clients with shorter timeouts may
cancel before export completes. Failure, timeout or an unavailable extra keeps
the Mermaid/text fallback. Normal cancellation reaps the worker before cleanup.
No caller-controlled output path or reusable file handle is exposed.

Output is capped at 500,000 UTF-8 bytes and validated again in the parent before
returning canonical XML. The static SVG allowlist rejects scripts, event handlers,
HTML/foreign objects, images, embedded CSS, external resources, animation, entity
declarations and unknown attributes. Only exact pinned GitHub source links are
allowed; link targets receive `noopener noreferrer`. Geometry, nesting, element
counts and viewport size are bounded. XML processing instructions are discarded
by canonical serialization. Unsupported output falls back with `SVG_UNSAFE`.

Other SVG errors include `SVG_UNAVAILABLE`, `SVG_VERSION`, `SVG_BUSY`,
`SVG_TIMEOUT`, `SVG_RESOURCE_LIMIT` and `SVG_OUTPUT_LIMIT`. Lower node/edge limits
for complex diagrams. This is resource isolation and static output validation,
not an OS sandbox. Windows x64/Python 3.12 is verified; other platforms are unverified.

## Execution limits and errors

Graph queries run one worker per server process, with a 45-second worker deadline,
a 1 GiB process memory budget and a 1,000,000-byte result cap. Additional concurrent
queries return `GRAPH_BUSY`. Cancellation kills/reaps the worker before removing
its temporary workspace, including acquisition files and parser caches. Worker
stdout/stderr are discarded, and only normalized fields reach the client.
The Windows Job Object limits committed memory; the POSIX implementation uses
`RLIMIT_AS`. Windows/Python 3.12 is verified; Linux/macOS remain unverified.
If memory limits cannot be installed, analysis fails closed. Process isolation
and Python audit hooks are not an OS security sandbox.

GitHub retrieval happens before extraction, using the existing token permissions.
Extraction then removes the token from its environment and denies Python socket
and process-launch audit events. It never imports or runs acquired source files.
There is no model processing or shared graph cache. Hard termination of the server
or cleanup failure may leave temporary files/workers; OS isolation remains the
local single-user access boundary.

Without the extra, `GRAPH_UNAVAILABLE` explains how to enable it. Other execution
errors include `GRAPH_VERSION`, `GRAPH_TIMEOUT`, `GRAPH_RESOURCE_LIMIT`,
`GRAPH_WORKER_FAILED`, `GRAPH_EXTRACTION_FAILED`, `GRAPH_OUTPUT_LIMIT`,
`FOCUS_NOT_FOUND`, input errors, and categorized GitHub acquisition errors.

## Snapshot analysis foundation

The internal acquisition API prepares temporary source files for graph
analysis. It resolves a commit once,
reads its Git tree and blob objects, and verifies downloaded blob identities.
It stages regular files without preserving Git executable modes and never extracts archives, follows
symlinks/submodules, or runs repository code, tests, hooks, or installers.

The initial profile includes `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, and `.cjs`
UTF-8 source files without NUL bytes. It skips common generated/vendor directories
(`.git`, `.venv`, `venv`, `node_modules`, `vendor`, `dist`, `build`, `__pycache__`)
and private directories (`.ssh`, `.aws`, `.local`), plus any path component named
`secrets`/`credentials` or starting with `.env`, `secrets.`, `credentials.`,
`id_rsa`, or `id_ed25519`. These are filename
rules, not secret detection; ordinary source may contain credentials. Repository
`.gitignore` rules are not interpreted; this profile operates on tracked Git files.
Other extensions, including upstream control/config files, are omitted.

Limits: 10,000 tree entries, 100 blob downloads, 1,000,000 bytes per file, and
5,000,000 downloaded file bytes per acquisition. Binary files still consume
download budgets. JSON response caps are 2 MB for revision/blob reads, 100 KB for
the pinned Git commit object, and 4 MB for the recursive tree (decimal units).
Truncated trees fail explicitly. Other omissions are counted by reason, with
deterministic path ordering. Unsafe paths or corrupt responses abort acquisition.
Portable paths are limited to 180 characters, 20 components and 100 characters
per component; Windows device names, case collisions and non-NFC paths fail.

Each acquisition uses a unique OS temporary directory, rechecks GitHub access and
deletes staged files on normal/context-error exit. There is no persistent cache,
reusable snapshot handle, or cross-request artifact sharing. Files live under the
server's OS identity; this is local single-user infrastructure. Forced termination
or storage cleanup failure can leave temporary files; secure the OS temp location.
The graph query's parent process enforces its worker deadline and cancellation.
Direct use of the internal acquisition API has only socket inactivity timeouts.

## Compatibility and limitations

The initial implementation pins official MCP Python SDK 1.30.0, whose latest
protocol revision is 2025-11-25. It is not a claim of support for newer protocol
revisions. Compatibility is verified with the SDK's Python stdio client; specific
IDE/desktop clients and non-Windows operating systems are not yet verified.
The local baseline is Windows with Python 3.12.13. Other operating systems and
specific IDE/desktop clients have not been verified. SDK 1.30.0 includes the
upstream settings/lifespan fix. Startup and test warnings are treated as errors.
Hosted CI is disabled by repository policy; local validation is used for PRs.

Repository listing and code search accept `page` (positive integer) and
`per_page` (1-100). Repeat with the suggested next page and the same page size.
A full repository page suggests checking for more; it does not guarantee another
page exists. Code search is restricted to the first 1,000 matches and reports
incomplete GitHub results. Directory listings are not paginated: GitHub's contents
endpoint caps them at 1,000 entries, and a full listing is flagged as potentially
incomplete. Search scopes now use properly separated `user:`/`repo:` qualifiers.

Requests use 3.05-second connect and 10-second read-inactivity timeouts, with at
most three attempts for transient connection/timeouts and selected 5xx responses.
Ordinary retries wait 1 then 2 seconds. Rate limits honor Retry-After/reset hints;
waits longer than 5 seconds return an actionable retry hint rather than sleeping.
Missing/invalid rate-limit hints default to 60 seconds. Read timeout is not a
whole-response deadline. See [GitHub's rate-limit guidance](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#handle-rate-limit-errors-appropriately).

Authentication, permission, not-found, invalid request, transport and malformed
response failures are reported without echoing HTTP bodies or exception details.
Public operations can run without a token; code search requires GitHub
authentication. Redirects are not followed; use a repository's canonical name if
it moved. Binary/large-file support is limited. This build
is intended for local development, not unattended production use.

## Development checks

Install the locked development tools, then run the local quality checks:

```powershell
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build
uv run --locked pytest
uv export --locked --no-emit-project --output-file dist/audit-requirements.txt --quiet
uv run --locked pip-audit --disable-pip --require-hashes --strict -r dist/audit-requirements.txt
```

Validate optional graph support with `uv run --locked --extra analysis pytest`.
Validate SVG support with `uv run --locked --extra svg pytest`.
The base suite checks missing-extra behavior; the analysis suite exercises the
real extractor on synthetic cross-file fixtures. Neither suite calls GitHub or
runs fixture code. To audit analysis dependencies too, add `--extra analysis` to
the `uv export` command above and audit the resulting hashed requirements. Use
`--extra svg` instead to include the SVG profile. Binary-wheel installation was
also checked in a fresh Windows environment using the exported locked runtime
requirements and the built wheel; no compiler toolchain was needed.

Build before testing: the suite checks package archives as well as tool behavior
and both installed entry points. Tests require no GitHub token, GitHub API calls,
or model. The dependency audit queries public vulnerability data for installed
third-party packages. It uses a fully hashed export of runtime and development
dependencies from uv.lock, excluding only this checkout's own package, and fails
on findings or audit errors. Pip-based dependency execution/resolution is disabled.

Hosted CI and required status-check gates are disabled for this repository.
The workflow definition is retained for optional future use. Before merging,
run local checks and verify installed-wheel startup as applicable. Main requires
pull requests, resolved conversations and linear history; force pushes and deletion
are blocked, including for administrators. No automatic publishing or deployment.

The root `server.py`, `requirements.txt`, and non-working web `Procfile` have been
replaced by the package, `pyproject.toml`, and `uv.lock`. Tool identifiers previously
contained spaces; update saved tool references to the identifiers listed above.
Human-readable titles remain available.

See [contribution guidelines](CONTRIBUTING.md) for submitting changes.
