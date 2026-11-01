"""Local stdio entry point; stdout belongs exclusively to the MCP transport."""

from github_mcp.server import mcp


def main() -> None:
    """Start the server using the official SDK's stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
