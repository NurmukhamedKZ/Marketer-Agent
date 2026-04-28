from fastmcp import FastMCP

mcp = FastMCP("Product Knowledge Base")

@mcp.tool
async def get_product_kb():