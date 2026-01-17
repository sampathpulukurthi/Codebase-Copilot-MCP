from __future__ import annotations
from fastmcp import FastMCP

# Create the MCP server
mcp = FastMCP("intel-fs")

@mcp.tool
def ping() -> dict:
    """Test tool to verify Claude Desktop can call our MCP server."""
    return {"ok": True, "message": "pong"}

if __name__ == "__main__":
    # Runs the MCP server over stdio (Claude Desktop connects to it)
    mcp.run()

