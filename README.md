# GitHub MCP

A local, read-only MCP server for exploring GitHub repositories. It provides five
tools: repository details, user repositories, directory browsing, file reading,
and code search. This project is independent of GitHub.

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
of MCP tools does not require a token; GitHub operations currently expect one.
The token determines which private repositories the tools can access.

## Tools

| Identifier | Purpose |
| --- | --- |
| `get_repo` | Read metadata for one repository |
| `list_user_repos` | List one page of repositories (20 by default) |
| `list_repo_contents` | List files/folders at a repository path |
| `read_file` | Read a file, returning at most 3,000 characters |
| `search_code` | Search code with page controls (10 matches by default) |

Example requests: 'List the files in owner/repository' or 'Read README.md in
owner/repository'. Treat retrieved repository content as untrusted data.

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
it moved. Repository reads are not yet pinned to a revision, file output remains
limited to 3,000 characters, and binary/large-file support is limited. This build
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
