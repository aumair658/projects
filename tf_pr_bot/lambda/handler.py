"""
GitHub App webhook receiver + Terraform PR reviewer.

Flow: verify webhook signature -> filter to pull_request events that touch
at least one *.tf file -> mint a GitHub App JWT and exchange it for an
installation token -> pull *every* .tf file in the repo at both the PR's
base and head SHAs -> run tfsec against each full tree -> diff the two
result sets so the comment only calls out findings the PR *introduces*,
while still surfacing how much pre-existing debt remains -> post as a PR
comment.

Full-tree (not diff-only) scanning is deliberate: a diff-only scan is
blind to vulnerable resources sitting in files the PR never touches.
Scanning both base and head and diffing is what avoids re-reporting that
same pre-existing debt on every single PR.

Runs as a Lambda behind a public Function URL (authorization_type=NONE) -
GitHub can't sign requests with AWS SigV4, so auth is the HMAC signature
check below instead, same as any self-hosted GitHub App webhook receiver.
"""

import base64
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import boto3
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_ssm = boto3.client("ssm")
_secret_cache: dict[str, str] = {}

GITHUB_API = "https://api.github.com"


def lambda_handler(event, context):
    raw_body = _raw_body(event)
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    if not _signature_valid(raw_body, headers.get("x-hub-signature-256", "")):
        return _response(401, "invalid signature")

    if headers.get("x-github-event") != "pull_request":
        return _response(200, "ignored: not a pull_request event")

    body = json.loads(raw_body)
    if body.get("action") not in ("opened", "synchronize", "reopened"):
        return _response(200, "ignored: action not reviewed")

    pr = body["pull_request"]
    repo = body["repository"]
    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]
    base_sha = pr["base"]["sha"]
    installation_id = body["installation"]["id"]

    token = _installation_token(installation_id)

    # Cheap early exit: don't pay for two full-tree scans on a PR that
    # doesn't touch Terraform at all (e.g. a docs-only or workflow-only PR).
    changed_files = _api_request(
        "GET", f"{GITHUB_API}/repos/{owner}/{repo_name}/pulls/{pr_number}/files", token
    )
    if not any(f["filename"].endswith(".tf") for f in changed_files):
        return _response(200, "ignored: no .tf changes")

    with tempfile.TemporaryDirectory() as base_dir, tempfile.TemporaryDirectory() as head_dir:
        _download_repo_tf_files(owner, repo_name, base_sha, token, base_dir)
        _download_repo_tf_files(owner, repo_name, head_sha, token, head_dir)

        base_findings = _run_tfsec(base_dir)
        head_findings = _run_tfsec(head_dir)

    new_findings, resolved_count, still_open_count = _diff_findings(base_findings, head_findings)

    comment = _format_comment(new_findings, resolved_count, still_open_count, head_sha)
    _api_request(
        "POST",
        f"{GITHUB_API}/repos/{owner}/{repo_name}/issues/{pr_number}/comments",
        token,
        body={"body": comment},
    )

    return _response(200, f"posted {len(new_findings)} new finding(s)")


# -----------------------------------------------------------------------------
# Webhook signature verification
# -----------------------------------------------------------------------------


def _raw_body(event) -> bytes:
    body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode()


def _signature_valid(raw_body: bytes, signature_header: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    secret = _get_secret(os.environ["GITHUB_WEBHOOK_SECRET_SSM"]).encode()
    expected = "sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# -----------------------------------------------------------------------------
# GitHub App auth: JWT (app identity) -> installation access token
# -----------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _build_app_jwt() -> str:
    app_id = os.environ["GITHUB_APP_ID"]
    private_key_pem = _get_secret(os.environ["GITHUB_APP_PRIVATE_KEY_SSM"]).encode()

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}"
        f".{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )

    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


def _installation_token(installation_id: int) -> str:
    app_jwt = _build_app_jwt()
    resp = _api_request(
        "POST",
        f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
        app_jwt,
    )
    return resp["token"]


# -----------------------------------------------------------------------------
# tfsec
# -----------------------------------------------------------------------------


def _download_repo_tf_files(owner: str, repo: str, ref: str, token: str, dest_dir: str) -> None:
    """Download every .tf file in the repo at `ref` into dest_dir, preserving
    the repo's directory layout so tfsec resolves cross-file references
    within that tree correctly."""
    tree = _api_request(
        "GET",
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{ref}?recursive=1",
        token,
    )
    tf_blobs = [
        entry
        for entry in tree.get("tree", [])
        if entry["type"] == "blob" and entry["path"].endswith(".tf")
    ]

    for entry in tf_blobs:
        blob = _api_request(
            "GET",
            f"{GITHUB_API}/repos/{owner}/{repo}/git/blobs/{entry['sha']}",
            token,
        )
        content = base64.b64decode(blob["content"])

        dest = os.path.join(dest_dir, entry["path"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(content)


def _run_tfsec(scan_dir: str) -> list[dict]:
    tfsec_path = os.environ.get("TFSEC_PATH", "/opt/bin/tfsec")
    result = subprocess.run(
        [tfsec_path, scan_dir, "--format", "json", "--soft-fail"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if not result.stdout.strip():
        return []
    parsed = json.loads(result.stdout)
    return parsed.get("results") or []


def _finding_key(finding: dict) -> tuple:
    # (rule, resource) rather than (rule, file, line) - a finding is "the
    # same" pre-existing issue even if an unrelated formatting change in
    # the PR shifts its line number.
    return (finding.get("rule_id", ""), finding.get("resource", ""))


def _diff_findings(
    base_findings: list[dict], head_findings: list[dict]
) -> tuple[list[dict], int, int]:
    base_keys = {_finding_key(f) for f in base_findings}
    head_keys = {_finding_key(f) for f in head_findings}

    new_findings = [f for f in head_findings if _finding_key(f) not in base_keys]
    resolved_count = len(base_keys - head_keys)
    still_open_count = len(base_keys & head_keys)

    return new_findings, resolved_count, still_open_count


def _format_comment(
    new_findings: list[dict], resolved_count: int, still_open_count: int, head_sha: str
) -> str:
    header = f"**tf_pr_bot (tfsec)** - full-repo scan at `{head_sha[:7]}`, diffed against the PR base."

    status_bits = []
    if new_findings:
        status_bits.append(f"{len(new_findings)} new finding(s) introduced by this PR")
    else:
        status_bits.append("no new findings introduced by this PR")
    if resolved_count:
        status_bits.append(f"{resolved_count} pre-existing finding(s) resolved")
    if still_open_count:
        status_bits.append(f"{still_open_count} pre-existing finding(s) still open")

    lines = [header, "", "- " + "\n- ".join(status_bits)]

    if new_findings:
        lines.append("")
        lines.append("New findings:")
        for r in new_findings:
            loc = r.get("location", {})
            filename = loc.get("filename", "?")
            start = loc.get("start_line", "?")
            severity = r.get("severity", "?")
            rule_id = r.get("rule_id", "?")
            description = r.get("description", "")
            lines.append(f"- **[{severity}] {rule_id}** `{filename}:{start}` - {description}")

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------


def _get_secret(name: str) -> str:
    if name not in _secret_cache:
        resp = _ssm.get_parameter(Name=name, WithDecryption=True)
        _secret_cache[name] = resp["Parameter"]["Value"]
    return _secret_cache[name]


def _api_request(method: str, url: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API {method} {url} failed: {e.code} {e.read().decode()}")


def _response(status: int, message: str):
    return {"statusCode": status, "body": json.dumps({"message": message})}
