from mcp.server.fastmcp import FastMCP

from github_mcp.github import gh

mcp = FastMCP("GitHub MCP")


def _valid_page(page: int, per_page: int) -> bool:
    return (
        type(page) is int
        and page > 0
        and type(per_page) is int
        and 1 <= per_page <= 100
    )


# TOOLS
@mcp.tool(name="get_repo", title="Get repository details")
def get_repo(owner: str, repo: str) -> str:
    """Get information about a GitHub repository."""
    data = gh(f"/repos/{owner}/{repo}")
    if not isinstance(data, dict):
        return "Unexpected response from GitHub"
    if "error" in data:
        return data["error"]
    if (
        not {
            "full_name",
            "stargazers_count",
            "forks_count",
            "html_url",
            "visibility",
            "created_at",
        }
        <= data.keys()
    ):
        return "Unexpected response from GitHub"
    return f"""
Repository: {data["full_name"]}
Description: {data.get("description", "No description")}
Stars: {data["stargazers_count"]}
Forks: {data["forks_count"]}
Language: {data.get("language", "Unknown")}
URL: {data["html_url"]}
Visibility: {data["visibility"]}
Created at: {data["created_at"]}
"""


@mcp.tool(name="list_user_repos", title="List user repositories")
def list_user_repos(
    username: str, sort: str = "updated", page: int = 1, per_page: int = 20
) -> str:
    """List one page of repositories for a GitHub user.

    Args:
        username: GitHub username.
        sort: GitHub sorting mode (default: updated).
        page: Positive page number (default: 1).
        per_page: Repositories per page, 1-100 (default: 20).
    """
    if not _valid_page(page, per_page):
        return "page must be positive and per_page must be between 1 and 100"
    data = gh(
        f"/users/{username}/repos",
        params={"sort": sort, "page": page, "per_page": per_page},
    )
    if isinstance(data, dict) and "error" in data:
        return data["error"]
    if not isinstance(data, list):
        return "Unexpected response from GitHub"
    if any(
        not isinstance(r, dict)
        or not isinstance(r.get("full_name"), str)
        or not {"stargazers_count", "forks_count"} <= r.keys()
        for r in data
    ):
        return "Unexpected response from GitHub"
    if not data:
        return "No repositories found."
    lines = [f"repos for user {username} (sorted by {sort}):"]
    for r in data:
        lines.append(
            f"- {r['full_name']} (Stars: {r['stargazers_count']}, Forks: {r['forks_count']}, Language: {r.get('language', 'Unknown')})"
        )
    lines.append(f"Page {page}; {len(data)} repositories returned.")
    if len(data) == per_page:
        lines.append(
            f"Page full; request page={page + 1}, per_page={per_page} to check for more."
        )
    return "\n".join(lines)


@mcp.tool(name="list_repo_contents", title="List repository contents")
def list_repo_contents(owner: str, repo: str, path: str = "") -> str:
    """Browse the files and folders inside a GitHub repository at a given path.

    Args:
        owner: GitHub username or org
        repo: Repository name
        path: Folder path to browse (default: '' for root)
    """
    data = gh(f"/repos/{owner}/{repo}/contents/{path}")
    if isinstance(data, dict) and "error" in data:
        return data["error"]
    if not isinstance(data, list):
        return "Unexpected response from GitHub"
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not isinstance(item.get("type"), str)
        for item in data
    ):
        return "Unexpected response from GitHub"
    lines = [f"Contents of {owner}/{repo}/{path or '(root)'}:\n"]
    for item in sorted(data, key=lambda x: (x["type"] != "dir", x["name"])):
        icon = "📁" if item["type"] == "dir" else "📄"
        size = f" ({item.get('size', 0)} bytes)" if item["type"] == "file" else ""
        lines.append(f"  {icon} {item['name']}{size}")
    if len(data) >= 1000:
        lines.append(
            "GitHub limits this endpoint to 1,000 directory entries; the listing may be incomplete."
        )
    return "\n".join(lines)


@mcp.tool(name="read_file", title="Read file")
def read_file(owner: str, repo: str, path: str) -> str:
    """Read the contents of a specific file in a GitHub repository.

    Args:
        owner: GitHub username or org
        repo: Repository name
        path: Full file path (e.g. 'src/index.py' or 'README.md')
    """
    import base64
    import binascii

    data = gh(f"/repos/{owner}/{repo}/contents/{path}")
    if not isinstance(data, dict):
        return "Unexpected response from GitHub"
    if "error" in data:
        return data["error"]
    if data.get("type") != "file":
        return f"'{path}' is not a file"
    if (
        not isinstance(data.get("content"), str)
        or type(data.get("size")) is not int
        or data.get("encoding", "base64") != "base64"
    ):
        return "File content unavailable or invalid"
    try:
        content = base64.b64decode(
            "".join(data["content"].split()), validate=True
        ).decode("utf-8", errors="replace")
    except (ValueError, binascii.Error):
        return "File content unavailable or invalid"
    # Cap at 3000 chars to keep responses readable
    if len(content) > 3000:
        content = (
            content[:3000] + f"\n\n... (truncated, full file is {data['size']} bytes)"
        )
    return f"File: {path}\n\n{content}"


@mcp.tool(name="search_code", title="Search code")
def search_code(
    query: str, owner: str = "", repo: str = "", page: int = 1, per_page: int = 10
) -> str:
    """Search for code across GitHub. Optionally scope to a specific repo.

    Args:
        query: Search term (e.g. 'FastMCP' or 'def handle_request')
        owner: Optional — limit to this user/org
        repo: Optional — limit to this repo (requires owner too)
        page: Positive page number (default: 1).
        per_page: Matches per page, 1-100 (default: 10); first 1,000 results only.
    """
    if not _valid_page(page, per_page) or page * per_page > 1000:
        return "Invalid page/per_page; search is limited to the first 1,000 results"
    if not query.strip() or (repo and not owner):
        return "Supply a non-empty query and an owner when specifying repo"
    q = query.strip()
    if owner and repo:
        q += f" repo:{owner}/{repo}"
    elif owner:
        q += f" user:{owner}"

    data = gh("/search/code", params={"q": q, "page": page, "per_page": per_page})
    if not isinstance(data, dict):
        return "Unexpected response from GitHub"
    if "error" in data:
        return data["error"]

    items = data.get("items", [])
    total = data.get("total_count", 0)
    if (
        not isinstance(items, list)
        or type(total) is not int
        or total < 0
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("html_url"), str)
            or not isinstance(item.get("repository"), dict)
            or not isinstance(item["repository"].get("full_name"), str)
            for item in items
        )
    ):
        return "Unexpected response from GitHub"
    if not items and not data.get("incomplete_results"):
        return "No results found." if page == 1 else f"No results on page {page}."
    lines = [f"Found {total} results for '{query}':\n"]
    for item in items:
        lines.append(f"  • {item['repository']['full_name']} → {item['path']}")
        lines.append(f"    {item['html_url']}\n")
    lines.append(f"Page {page}; {len(items)} matches returned.")
    if page * per_page < min(total, 1000):
        lines.append(f"Continue with page={page + 1}, per_page={per_page}.")
    if data.get("incomplete_results"):
        lines.append("GitHub reports incomplete search results; narrow the query.")
    return "\n".join(lines)
