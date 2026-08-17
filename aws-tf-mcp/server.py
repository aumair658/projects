"""
aws-tf-mcp: a learning project for building an MCP server around AWS/Terraform.

MCP (Model Context Protocol) servers expose "tools" that an AI client
(like Claude) can call. Each tool is just a Python function with a
docstring and type hints -- the `@mcp.tool()` decorator handles turning
that into something the client can discover and invoke.

This starter has ONE working tool: `list_terraform_resources`. It reads
.tf files in a directory and extracts resource declarations with a
regex -- no AWS credentials needed, so you can run and test the whole
loop (server -> tool call -> result) before adding anything that talks
to real AWS.

Run it locally with the MCP inspector to see this in action:

    pip install -r requirements.txt
    mcp dev server.py

Then call list_terraform_resources with directory="../tf_pr_reviewer"
(the sibling project in this monorepo has real .tf files to point at).

--- Roadmap: tools to add yourself as you learn ---

1. (done) list_terraform_resources -- static file parsing, no AWS calls.
2. list_s3_buckets -- your first live AWS call. Use boto3, and keep it
   read-only (`s3.list_buckets()`). This is where you'll learn how
   credentials/auth flow into an MCP server's process.
3. terraform_plan_summary -- shell out to `terraform plan` in a given
   directory (subprocess) and return a parsed summary of adds/changes/
   destroys. This teaches wrapping an external CLI tool as an MCP tool,
   which is the same pattern real infra tools use.

Each new tool is just another `@mcp.tool()` function below -- copy the
shape of list_terraform_resources and go from there.
"""

import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aws-tf-mcp")

_RESOURCE_RE = re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"', re.MULTILINE)


@mcp.tool()
def list_terraform_resources(directory: str) -> list[str]:
    """List all Terraform resources declared in .tf files under a directory.

    Args:
        directory: Path to a directory containing .tf files (e.g. a
            sibling Terraform project like "../tf_pr_reviewer").

    Returns:
        A list of "type.name" strings, one per resource block found,
        e.g. ["aws_s3_bucket.example", "aws_security_group.example"].
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"not a directory: {directory}")

    resources = []
    for tf_file in sorted(root.glob("*.tf")):
        text = tf_file.read_text()
        for resource_type, resource_name in _RESOURCE_RE.findall(text):
            resources.append(f"{resource_type}.{resource_name}")
    return resources


if __name__ == "__main__":
    mcp.run()
