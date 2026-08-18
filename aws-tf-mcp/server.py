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
3. (done) terraform_plan_summary -- shell out to `terraform plan -json`
   (subprocess) and parse the streamed JSON-lines output for the one
   "change_summary" event, rather than regexing the human-readable
   text. This is the same pattern tools like Atlantis/Terraform Cloud
   use, and it's more robust than text-scraping since the JSON schema
   is stable across Terraform versions where wording isn't.
4. (done) aws-resources:// -- MCP's other primitive: a Resource.
   Tools are functions a client *calls*, with arguments, to perform an
   action. Resources are read-only content a client *reads* directly
   by URI (discovered via resources/list, fetched via resources/read)
   -- no arguments, no "invocation". `@mcp.resource(uri)` is the
   decorator, mirroring `@mcp.tool()`.
5. (done) tfsec_scan -- shell out to `tfsec` (subprocess), same
   pattern as terraform_plan_summary. No new MCP concept here -- the
   point is reusing an existing CLI-wrapping tool (tf_pr_bot's Lambda
   handler runs the exact same tfsec invocation against PR diffs) as
   a callable MCP tool instead of a webhook-triggered scan.

Each new tool is just another `@mcp.tool()` function below -- copy the
shape of list_terraform_resources and go from there.
"""

import json
import re
import subprocess
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


# Terraform's plan action names, grouped into the buckets we report.
# "create-then-delete"/"delete-then-create" are both a replace (the
# resource can't be updated in place, so Terraform destroys and
# recreates it); "no-op" resources are left out of the report entirely
# since nothing is actually changing for them.
_PLAN_ACTION_BUCKETS = {
    "create": "add",
    "update": "change",
    "delete": "destroy",
    "read": "read",
    "create-then-delete": "replace",
    "delete-then-create": "replace",
}


@mcp.tool()
def terraform_plan_summary(directory: str) -> dict:
    """Run `terraform plan` in a directory and list what it would change.

    Read-only: `terraform plan` only compares the .tf config against
    real infrastructure state, it never applies anything. The
    directory must already be `terraform init`-ed (this tool doesn't
    init it for you), and needs reachable AWS credentials since a real
    plan refreshes state against the live account -- same credential
    resolution as list_s3_buckets/list_ec2/etc. above.

    Parses `terraform plan -json`'s streamed output rather than the
    human-readable text: Terraform emits one JSON object per line, and
    each resource's planned action shows up as its own "planned_change"
    event (with a "change_summary" event at the end totaling them up)
    -- the same events Atlantis/Terraform Cloud key off of, and more
    stable across Terraform versions than scraping the "Plan: N to
    add, ..." text line or trying to grep it yourself.

    Args:
        directory: Path to an already-`terraform init`-ed directory
            (e.g. "../tf_pr_reviewer").

    Returns:
        A dict like {"summary": "Plan: 1 to add, 1 to change, 0 to
        destroy.", "add": ["aws_s3_bucket.new"], "change": [...],
        "destroy": [], "read": [], "replace": []} -- resource
        addresses grouped by planned action.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"not a directory: {directory}")

    result = subprocess.run(
        ["terraform", "plan", "-json", "-no-color", "-input=false"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"terraform plan failed:\n{result.stderr or result.stdout}")

    report: dict[str, list[str]] = {bucket: [] for bucket in ("add", "change", "destroy", "read", "replace")}
    summary = ""
    for line in result.stdout.splitlines():
        event = json.loads(line)
        event_type = event.get("type")
        if event_type == "planned_change":
            bucket = _PLAN_ACTION_BUCKETS.get(event["change"]["action"])
            if bucket:
                report[bucket].append(event["change"]["resource"]["addr"])
        elif event_type == "change_summary":
            summary = event.get("@message", "")

    if not summary:
        raise RuntimeError("terraform plan produced no change_summary event")

    return {"summary": summary, **report}


@mcp.resource("aws-resources://by-type")
def aws_resource_inventory() -> dict[str, list[str]]:
    """The AWS account's tagged resources, grouped by type -- as a Resource.

    Same data and same read-only Resource Groups Tagging API call as
    the list_all_resources_by_type tool above (reused directly, no
    duplicated logic) -- the point isn't new data, it's the other MCP
    primitive: a client reads this by URI (aws-resources://by-type)
    rather than calling it with arguments. Good fit for a Resource
    since the underlying data already takes no parameters and has no
    side effects -- exactly what Resources are meant for.

    Returns:
        Same shape as list_all_resources_by_type(): a dict mapping a
        "service:resource-type" label to a list of resource ARNs.
    """
    return list_all_resources_by_type()


@mcp.tool()
def tfsec_scan(directory: str) -> list[dict]:
    """Run tfsec against a directory and return its security findings.

    Read-only static analysis: tfsec only reads .tf files, it never
    touches real infrastructure or needs AWS credentials -- same shape
    as list_terraform_resources (local file analysis) but flagging
    security issues instead of just inventorying resources. Requires
    the tfsec CLI to be installed and on PATH.

    This is the same tfsec invocation (`--format json --soft-fail`)
    that tf_pr_bot's Lambda handler runs against PR diffs -- see
    `_run_tfsec()` in tf_pr_bot/lambda/handler.py -- wrapped as a
    tool here instead of a webhook-triggered scan.

    Args:
        directory: Path to a directory containing .tf files (e.g.
            "../tf_pr_reviewer").

    Returns:
        A list of findings, each a dict with "rule_id", "resource",
        "severity", "description", "file", and "line". Empty list if
        tfsec finds nothing.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"not a directory: {directory}")

    result = subprocess.run(
        ["tfsec", str(root), "--format", "json", "--soft-fail"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tfsec failed:\n{result.stderr or result.stdout}")
    if not result.stdout.strip():
        return []

    parsed = json.loads(result.stdout)
    findings = []
    for f in parsed.get("results") or []:
        location = f.get("location", {})
        findings.append({
            "rule_id": f.get("rule_id", ""),
            "resource": f.get("resource", ""),
            "severity": f.get("severity", ""),
            "description": f.get("description", ""),
            "file": location.get("filename", ""),
            "line": location.get("start_line", ""),
        })
    return findings


if __name__ == "__main__":
    mcp.run()
