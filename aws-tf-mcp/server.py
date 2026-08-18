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
2. (done) list_s3_buckets -- your first live AWS call, via boto3.
   boto3 resolves credentials the same way the AWS CLI does (env vars,
   ~/.aws/credentials, or an IAM role) -- the MCP server itself never
   handles a key or secret directly, it just inherits whatever identity
   the process it's running in already has.
3. terraform_plan_summary -- shell out to `terraform plan` in a given
   directory (subprocess) and return a parsed summary of adds/changes/
   destroys. This teaches wrapping an external CLI tool as an MCP tool,
   which is the same pattern real infra tools use.

Each new tool is just another `@mcp.tool()` function below -- copy the
shape of list_terraform_resources and go from there.
"""

import re
from pathlib import Path

import boto3
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


@mcp.tool()
def list_s3_buckets() -> list[str]:
    """List the names of all S3 buckets in the AWS account.

    Read-only: calls the S3 ListBuckets API. Uses whatever AWS
    credentials boto3 finds in the environment (same resolution order
    as the AWS CLI: env vars, ~/.aws/credentials, then an IAM role).

    Returns:
        A list of bucket names, e.g. ["my-app-data", "my-logs"].
    """
    s3 = boto3.client("s3")
    response = s3.list_buckets()
    return [bucket["Name"] for bucket in response["Buckets"]]

@mcp.tool()
def list_lambda_functions() -> list[str]:
    """List the names of all Lambda functions in the AWS account.

    Read-only: calls the Lambda ListFunctions API. Uses whatever AWS
    credentials boto3 finds in the environment (same resolution order
    as the AWS CLI: env vars, ~/.aws/credentials, then an IAM role).

    Returns:
        A list of function names, e.g. ["my-function-1", "my-function-2"].
    """
    lambda_client = boto3.client("lambda")
    response = lambda_client.list_functions()
    return [func["FunctionName"] for func in response["Functions"]]

@mcp.tool()
def list_ec2() -> list[str]:
    """List the names of all EC2 instances in the AWS account.

    Read-only: calls the EC2 DescribeInstances API. Uses whatever AWS
    credentials boto3 finds in the environment (same resolution order
    as the AWS CLI: env vars, ~/.aws/credentials, then an IAM role).

    Returns:
        A list of instance names, e.g. ["i-0123456789abcdef0", "i-0123456789abcdef1"].
    """
    ec2 = boto3.client("ec2")
    response = ec2.describe_instances()
    instance_names = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            instance_names.append(instance["InstanceId"])
    return instance_names


def _resource_type_from_arn(arn: str) -> str:
    """Best-effort "service:resource-type" label from an ARN.

    ARN shapes vary by service, e.g.:
        arn:aws:s3:::my-bucket                        -> "s3:bucket"
        arn:aws:lambda:us-east-1:123:function:my-func  -> "lambda:function"
        arn:aws:ec2:us-east-1:123:instance/i-0123      -> "ec2:instance"
    This is a heuristic, not a full ARN parser -- it's enough to group
    by, not to reconstruct the ARN. S3 is special-cased: its ARNs have
    no resource-type segment (just the bucket name), so without the
    special case every bucket would land in its own one-item "type".
    """
    parts = arn.split(":", 5)
    service = parts[2] if len(parts) > 2 else "unknown"
    if service == "s3":
        return "s3:bucket"
    remainder = parts[5] if len(parts) > 5 else ""
    resource_type = re.split(r"[/:]", remainder, maxsplit=1)[0] if remainder else "resource"
    return f"{service}:{resource_type}"


@mcp.tool()
def list_all_resources_by_type() -> dict[str, list[str]]:
    """List all tagged resources in the AWS account, grouped by resource type.

    Read-only: calls the Resource Groups Tagging API (GetResources),
    which enumerates resources across most AWS services in one call --
    unlike list_s3_buckets / list_lambda_functions / list_ec2 above,
    which each query one service's own API individually.

    Caveat: this API only returns resources that are currently tagged,
    or were tagged recently (AWS keeps them visible for a short grace
    period after tags are removed). A resource that's never been
    tagged won't show up here -- that's a real limitation of this API,
    not a bug in this tool. list_ec2/list_s3_buckets/etc. above don't
    have this limitation since they ask each service directly.

    Returns:
        A dict mapping a "service:resource-type" label (e.g.
        "ec2:instance", "lambda:function") to a list of that type's
        resource ARNs.
    """
    client = boto3.client("resourcegroupstaggingapi")
    grouped: dict[str, list[str]] = {}

    paginator = client.get_paginator("get_resources")
    for page in paginator.paginate():
        for mapping in page["ResourceTagMappingList"]:
            arn = mapping["ResourceARN"]
            resource_type = _resource_type_from_arn(arn)
            grouped.setdefault(resource_type, []).append(arn)

    return grouped


if __name__ == "__main__":
    mcp.run()
