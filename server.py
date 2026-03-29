import os
import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GitHub MCP")


# The constants below are used to interact with the GitHub API. The TOKEN is expected to be set as an environment variable for authentication purposes.
GITHUB_API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# reusable helper function to make GET requests to the GitHub API. It takes a path and an optional dictionary of parameters, and returns the JSON response as a dictionary or list. instead of copy-pasting requests.get(...) with all the headers in every single tool, you write it once here and call gh(...) everywhere
def gh(path:str, params:dict={})->dict | list: #path-> api endpoint , params-> query parameters
    """Helper function to make GET requests to the GitHub API."""
    res = requests.get(f"{GITHUB_API}{path}", headers=HEADERS, params=params) # make a GET request to the GitHub API with the specified path and parameters
    if res.status_code == 404:
        return {"error": "Not found"}
    if res.status_code == 401:
        return {"error": "Invalid or missing GITHUB_TOKEN"}
    if not res.ok:
        return {"error": f"GitHub API error: {res.status_code}: {res.text[:200]}"}
    return res.json() # return the JSON response as a dictionary or list


#TOOLS 
@mcp.tool("Get repositories for a user")
def get_repo(owner: str, repo: str)->str:
    """Get information about a GitHub repository."""
    data= gh(f"/repos/{owner}/{repo}")
    if "error" in data:
        return data["error"]
    return f"""
Repository: {data['full_name']}
Description: {data.get('description', 'No description')}
Stars: {data['stargazers_count']}
Forks: {data['forks_count']}
Language: {data.get('language', 'Unknown')}
URL: {data['html_url']}
Visibility: {data['visibility']}
Created at: {data['created_at']}
"""


@mcp.tool("List user repositories")
def list_user_repos(username: str, sort:str="updated")->str:
    """List repositories for a GitHub user."""
    data = gh(f"/users/{username}/repos", params={"sort": sort, "per_page": 20})
    if isinstance(data, dict) and "error" in data:
        return data["error"]
    if not data:
        return "No repositories found."
    lines = [f"repos for user {username} (sorted by {sort}):"]
    for r in data:
        lines.append(f"- {r['full_name']} (Stars: {r['stargazers_count']}, Forks: {r['forks_count']}, Language: {r.get('language', 'Unknown')})")
    return "\n".join(lines)

@mcp.tool("List repository contents")
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
    lines = [f"Contents of {owner}/{repo}/{path or '(root)'}:\n"]
    for item in sorted(data, key=lambda x: (x['type'] != 'dir', x['name'])):
        icon = "📁" if item['type'] == 'dir' else "📄"
        size = f" ({item.get('size', 0)} bytes)" if item['type'] == 'file' else ""
        lines.append(f"  {icon} {item['name']}{size}")
    return "\n".join(lines)


@mcp.tool("Read file")
def read_file(owner: str, repo: str, path: str) -> str:
    """Read the contents of a specific file in a GitHub repository.
 
    Args:
        owner: GitHub username or org
        repo: Repository name
        path: Full file path (e.g. 'src/index.py' or 'README.md')
    """
    import base64
    data = gh(f"/repos/{owner}/{repo}/contents/{path}")
    if isinstance(data, dict) and "error" in data:
        return data["error"]
    if data.get("type") != "file":
        return f"'{path}' is not a file"
    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    # Cap at 3000 chars to keep responses readable
    if len(content) > 3000:
        content = content[:3000] + f"\n\n... (truncated, full file is {data['size']} bytes)"
    return f"File: {path}\n\n{content}"

