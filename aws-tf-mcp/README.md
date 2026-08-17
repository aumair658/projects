# aws-tf-mcp

A learning project: building an [MCP](https://modelcontextprotocol.io)
(Model Context Protocol) server from scratch, in the AWS/Terraform domain
this monorepo already lives in. The goal isn't a polished tool -- it's to
understand what an MCP server actually *is* by building one up in stages,
each stage introducing one new concept.

## What's an MCP server, briefly

An MCP server is a small process that exposes **tools** (functions) an AI
client -- Claude, in this case -- can discover and call. The client sends
a request, the server runs the matching Python function, and the result
goes back to the client as the tool's output. That's the whole loop:
discover tools -> call a tool -> get a result. Everything else (resources,
prompts, auth) builds on top of that.

This project uses the official Python SDK's `FastMCP`, which turns a
plain function into a tool with one decorator -- see `server.py`.

## What's here now

One tool, `list_terraform_resources`, which reads `.tf` files in a
directory and regex-extracts `resource "type" "name"` blocks. It makes
no network or AWS calls, so it's the simplest possible thing to run and
see actually work end to end.

## Running it

```bash
python3 -m venv .venv
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
2. **Next** -- `list_s3_buckets`: your first live AWS call via `boto3`
   (`pip install boto3` first). Keep it read-only. This is where you'll
   run into how AWS credentials reach a process that isn't the AWS CLI.
3. **After that** -- `terraform_plan_summary`: shell out to
   `terraform plan` with `subprocess` and parse its output. This is the
   same "wrap a CLI tool as an MCP tool" pattern real infra-focused MCP
   servers use.

From there, natural next steps once the basics feel solid: multiple AWS
services, a resource (not just tools) exposing read-only state, or
tying this into `tf_pr_bot`'s tfsec scan as a callable tool.
