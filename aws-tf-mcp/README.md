# aws-tf-mcp

A learning project: building an [MCP](https://modelcontextprotocol.io)
(Model Context Protocol) server from scratch, in the AWS/Terraform domain
this monorepo already lives in. The goal isn't a polished tool -- it's to
understand what an MCP server actually *is* by building one up in stages,
each stage introducing one new concept.

## What's an MCP server, briefly

An MCP server is a small process that exposes **tools** (functions) and
**resources** (read-only content addressed by URI) that an AI client --
Claude, in this case -- can discover and use. For a tool, the client sends
a request with arguments, the server runs the matching Python function,
and the result goes back as the tool's output. For a resource, the client
just reads it directly by URI -- no arguments, no "invocation", since it's
meant to be read-only content rather than an action. Everything else
(prompts, auth) builds on top of these two.

This project uses the official Python SDK's `FastMCP`, which turns a
plain function into a tool or a resource with one decorator each --
`@mcp.tool()` / `@mcp.resource(uri)` -- see `server.py`.

## What's here now

- `list_terraform_resources` -- reads `.tf` files in a directory and
  regex-extracts `resource "type" "name"` blocks. No network or AWS
  calls, so it's the simplest possible thing to run and see actually
  work end to end.
- `list_s3_buckets`, `list_lambda_functions`, `list_ec2` -- each calls
  one AWS service's own read-only list/describe API via `boto3` and
  returns the resource names/IDs. Credentials aren't passed as
  arguments -- boto3 finds them itself (see the docstring in
  `server.py` for the resolution order).
- `list_all_resources_by_type` -- calls the Resource Groups Tagging
  API once and groups every tagged resource by `service:resource-type`.
  Broader than the per-service tools above, but only sees resources
  that are (or were recently) tagged.
- `terraform_plan_summary` -- shells out to `terraform plan -json` in
  an already-`init`-ed directory and parses the streamed JSON-lines
  output into resource addresses grouped by planned action, e.g.
  `{"summary": "Plan: 1 to add, 1 to change, 0 to destroy.",
  "add": ["aws_s3_bucket.new"], "change": [...], "destroy": [],
  "read": [], "replace": []}`. Read-only (a plan never applies), but
  needs both a real Terraform init and reachable AWS credentials since
  it refreshes state against the live account.
- `aws-resources://by-type` -- a **Resource**, not a tool: the same
  data as `list_all_resources_by_type` (it just calls that function),
  but read directly by URI instead of invoked with arguments. Exists
  to demonstrate MCP's other primitive using data you already
  understand, not to add new functionality.
- `tfsec_scan` -- shells out to `tfsec` (same `--format json
  --soft-fail` invocation [`tf_pr_bot`](../tf_pr_bot/README.md)'s
  Lambda handler runs) and returns findings as a list of dicts with
  `rule_id`/`resource`/`severity`/`description`/`file`/`line`. No AWS
  needed -- tfsec is a static analyzer, same "local file, no
  credentials" shape as `list_terraform_resources`.

## Running it

```bash
cd aws-tf-mcp
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mcp dev server.py
```

`mcp dev` launches the MCP Inspector (a browser UI) connected to this
server. From there you can call `list_terraform_resources` directly --
point it at `../tf_pr_reviewer` (the sibling project in this monorepo
has real `.tf` files with an S3 bucket and a security group) and you
should get back a list like:

```
["aws_s3_bucket.example", "aws_security_group.example"]
```

To connect it to Claude Code instead of the Inspector, add it as a local
MCP server pointing at `server.py` (see `claude mcp add` docs) once
you've got it running standalone first.

## Testing

There's no automated test suite (see CI below for what does run
automatically) -- this project is meant to be exercised by hand as you
build each tool:

- **No AWS needed**: `list_terraform_resources` is the one tool that
  makes no network calls, so it's the fastest way to confirm the
  server itself is wired up right:
  ```bash
  .venv/bin/python3 -c "
  import server
  print(server.list_terraform_resources('../tf_pr_reviewer'))
  "
  ```
  Should print the 4 resources in `tf_pr_reviewer`'s `.tf` files.
- **With AWS creds**: same pattern for the rest, e.g.
  `server.terraform_plan_summary('../tf_pr_reviewer')` (needs
  `tf_pr_reviewer` to already be `terraform init`-ed) or
  `server.list_all_resources_by_type()`.
- **`tfsec_scan`** needs no AWS creds either, just the `tfsec` CLI on
  PATH: `server.tfsec_scan('../tf_pr_reviewer')` should return 9
  findings, including the two `INTENTIONAL FINDING`s called out in
  that project's README.
- **The Resource, not a tool** -- `read_resource`/`list_resources` are
  async and go through `server.mcp`, not the plain function call above:
  ```bash
  .venv/bin/python3 -c "
  import asyncio, server
  print(asyncio.run(server.mcp.list_resources()))
  print(asyncio.run(server.mcp.read_resource('aws-resources://by-type')))
  "
  ```
- **Full protocol, interactively**: `mcp dev server.py` (see "Running
  it" above) -- the Inspector lets you call every tool/resource through
  the actual MCP client/server loop, not just the underlying Python
  function.

## CI

`../.github/workflows/aws-tf-mcp-smoke-test.yml` (monorepo root -- GitHub
only reads workflows from there, not per-subdirectory) runs on every
push/PR touching this project: installs `requirements.txt` into a clean
venv and does `python -c "import server"`. There's no test suite yet, so
this is just an import smoke test -- enough to catch a syntax error, a
missing/renamed dependency, or a broken `@mcp.tool()` decorator before
merge. It needs no AWS/Terraform credentials since none of that runs at
import time, only when a tool is actually called.

The repo-wide `security-scan.yml` (Trivy + Bandit, see the root README)
also covers this project automatically, for CVEs/secrets/IaC issues
rather than "does it still run."

## Roadmap -- build these next as you learn

Each step is deliberately a small jump from the last. Full detail on
what each teaches is in the docstring at the top of `server.py`.

1. **Done** -- `list_terraform_resources`: static file parsing, the
   `@mcp.tool()` basics, no external dependencies.
2. **Done** -- `list_s3_buckets`: your first live AWS call via `boto3`.
   Read-only, and shows how credentials reach a process that isn't the
   AWS CLI (boto3 uses the same env-vars / `~/.aws/credentials` / IAM
   role resolution order the CLI does).
3. **Done** -- `terraform_plan_summary`: shells out to
   `terraform plan -json` with `subprocess` and parses the streamed
   JSON-lines output -- each resource's planned action is its own
   "planned_change" event -- into resource addresses grouped by
   add/change/destroy/read/replace, rather than regexing the
   human-readable text. Same pattern tools like Atlantis/Terraform
   Cloud use, and stable across Terraform versions where the text
   wording isn't.
4. **Done** -- `aws-resources://by-type`: MCP's other primitive, a
   Resource. Same underlying data and API call as
   `list_all_resources_by_type` (reused directly), but read by URI
   instead of called with arguments -- the concept being learned here
   is the tool-vs-resource distinction, not new data.
5. **Done** -- `tfsec_scan`: shells out to `tfsec` (subprocess), the
   same pattern as `terraform_plan_summary`. No new MCP concept here --
   the point is wrapping `tf_pr_bot`'s existing scan (its Lambda
   handler runs the identical `tfsec ... --format json --soft-fail`
   invocation against PR diffs) as a callable tool instead of a
   webhook-triggered one.
