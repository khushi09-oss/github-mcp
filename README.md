# GitHub MCP Server 

A Python MCP (Model Context Protocol) server that gives Claude the ability to browse GitHub repositories and search code — in real time, directly from chat.

Built with [FastMCP](https://github.com/modelcontextprotocol/python-sdk) · Deployed on Railway · No setup needed to connect

>  **In progress** — Issues & PR tools coming soon.

---

## Connect instantly

Add this URL as a **Custom Connector** in Claude (Pro/Team plan):

```
git-hub-mcp.up.railway.app
```

> **Note:** This server uses a shared GitHub token scoped to public repositories only.
> For private repo access or heavy usage, deploy your own instance (see [Self-hosting](#self-hosting)).

---

## What Claude can do with this MCP

### Browse repos & files
- Get full details about any public repository — stars, forks, language, open issues
- List all public repositories for any GitHub user
- Browse the file and folder tree of any repo at any path
- Read the actual contents of any file (README, source code, configs)

### Search code & commits
- Search for code across all of GitHub by keyword
- Scope searches to a specific user or repository
- Find repositories by keyword, filtered by language

---

## Example prompts

Once connected, just talk to Claude naturally:

```
Show me all repos for user sanket-164, sorted by most recently updated
```
```
Search for MCP server Python repos on GitHub, sorted by stars
```
```
Read the README.md from microsoft/vscode
```
```
Browse the files inside sanket-164/MCP-Servers
```
```
Search for "FastMCP" in the sanket-164/MCP-Servers repo
```
```
Find Python repos about machine learning on GitHub
```

---

## Tools reference

| Tool | Description | Key inputs |
|---|---|---|
| `get_repo` | Repository details — stars, forks, language, last push | `owner`, `repo` |
| `list_user_repos` | All public repos for a GitHub user | `username`, `sort` |
| `list_repo_contents` | Browse files and folders at any path | `owner`, `repo`, `path` |
| `read_file` | Read a file's full contents | `owner`, `repo`, `path` |
| `search_code` | Search code across GitHub, optionally scoped to a repo | `query`, `owner?`, `repo?` |

### Coming soon
| Tool | Description |
|---|---|
| `list_commits` | Recent commits on any branch |
| `search_repos` | Find repos by keyword and language |
| `list_issues` | Open or closed issues in a repo |
| `get_issue` | Full details of a specific issue |
| `list_pull_requests` | Open or closed PRs in a repo |
| `get_pull_request` | Full PR details with diff stats |

---

## Self-hosting

Deploy your own instance with your own GitHub token for private repo access and no rate-limit sharing.

### Prerequisites

- Python 3.10+
- A GitHub personal access token ([create one here](https://github.com/settings/tokens))
  - For public repos only: no scopes needed
  - For private repos: enable the `repo` scope

### Run locally (Claude Desktop — free)

**1. Clone and install**

```bash
git clone https://github.com/YOUR_USERNAME/github-mcp.git
cd github-mcp
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Switch to STDIO transport**

In `server.py`, change the last line to:

```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**3. Add to Claude Desktop config**

Find your config file:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add this entry (use absolute paths):

```json
{
  "mcpServers": {
    "github": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["/absolute/path/to/github-mcp/server.py"],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

**4. Restart Claude Desktop** — your tools will appear automatically.

---

### Deploy to Railway (Claude Pro/Team — HTTP)

**1. Push to GitHub**

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/github-mcp.git
git push -u origin main
```

**2. Deploy on Railway**

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your `github-mcp` repo — Railway auto-detects Python via the `Procfile`

**3. Add your GitHub token**

In Railway, click your service card → **Variables** tab → **New Variable**:

```
GITHUB_TOKEN = ghp_your_token_here
```

Railway will automatically redeploy with the token set.

**4. Get your live URL**

Click your service card → **Settings** tab → **Networking** → **Generate Domain**

You'll get a URL like:
```
https://github-mcp-production.up.railway.app
```

**5. Connect to Claude**

In Claude.ai → tools icon → **Add more tools → Custom connector** → paste:

```
https://github-mcp-production.up.railway.app/mcp
```

Click **Save** → **Always Allow**.

---

## Test with MCP Inspector (no Claude needed)

```bash
pip install "mcp[cli]"
mcp inspect server.py
```

This opens a browser UI where you can call every tool directly and see the raw responses — great for debugging before connecting to Claude.

---

## Project structure

```
github-mcp/
├── server.py          # MCP tools (5 tools currently)
├── requirements.txt   # mcp[cli], requests
├── Procfile           # Railway start command
└── README.md
```

---

## Built with

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — FastMCP server framework
- [GitHub REST API](https://docs.github.com/en/rest) — v2022-11-28
- [Railway](https://railway.app) — deployment platform
