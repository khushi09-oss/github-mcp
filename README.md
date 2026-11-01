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
| `list_user_repos` | List up to 20 repositories returned for a username |
| `list_repo_contents` | List files/folders at a repository path |
| `read_file` | Read a file, returning at most 3,000 characters |
| `search_code` | Return up to 10 GitHub code-search matches |

Example requests: 'List the files in owner/repository' or 'Read README.md in
owner/repository'. Treat retrieved repository content as untrusted data.

## Compatibility and limitations

The initial implementation pins official MCP Python SDK 1.30.0, whose latest
protocol revision is 2025-11-25. It is not a claim of support for newer protocol
revisions. Compatibility is verified with the SDK's Python stdio client; specific
IDE/desktop clients and non-Windows operating systems are not yet verified.
The local baseline is Windows with Python 3.12.13. The CI workflow targets
Windows and Ubuntu with the same Python version; hosted results are pending its
first run. SDK 1.30.0 includes the upstream fix for the settings/lifespan warning.
Startup and test warnings are treated as errors.

The existing API tools still have prototype limitations: no pagination or
revision-pinned reads, no request timeouts/retries, and incomplete network-error
handling. Scoped search currently constructs qualifiers incorrectly; use an
unscoped query or include a properly spaced `repo:owner/name` qualifier in `query`
while leaving `owner`/`repo` empty. Binary/large files may be unsupported. This
build is intended for local development; it is not ready for unattended use.

## Development checks

Install the locked development tools, then run the same gates used by CI:

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

CI runs these checks on pull requests and branch pushes, then reinstalls the
built wheel and repeats startup tests without re-syncing the editable package.
The workflow uses read-only repository permissions, pinned actions and uv, and
performs no publishing or deployment. Branch protection is not yet configured.

The root `server.py`, `requirements.txt`, and non-working web `Procfile` have been
replaced by the package, `pyproject.toml`, and `uv.lock`. Tool identifiers previously
contained spaces; update saved tool references to the identifiers listed above.
Human-readable titles remain available.

See [contribution guidelines](CONTRIBUTING.md) for submitting changes.
