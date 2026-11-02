# GitHub MCP

A local, read-only MCP server for exploring GitHub repositories. Its seven tools
provide repository details, browsing, search, and commit-pinned file reading with
source links and continuation. This project is independent of GitHub.

## Install from this checkout

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).
This is an early local build, not a published package or hosted endpoint.

```powershell
uv sync --locked
```

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

## Snapshot analysis foundation

The internal acquisition API prepares temporary source files for future graph
analysis; it adds no MCP tool or graph dependency yet. It resolves a commit once,
reads its Git tree and blob objects, and verifies downloaded blob identities.
It creates regular, non-executable files and never extracts archives, follows
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
Hard whole-operation deadlines and worker cancellation remain future work.

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
