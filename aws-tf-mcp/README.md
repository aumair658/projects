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

From there, a natural next step: tying `tf_pr_bot`'s tfsec scan in as
a callable tool, the same "wrap a CLI tool" pattern used for
`terraform_plan_summary`.
