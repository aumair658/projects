# aws_resume — Plan & Task Tracker

An AWS-hosted resume site, built with AI assistance but gated by a secure
CI/CD pipeline. This file is the single source of truth for what's done,
what's in progress, and what's next.

**Status legend:** `[x]` done · `[~]` in progress · `[ ]` not started

---

## How the AI tooling is split

Different mechanisms for different jobs — not everything should be an agent.

| Mechanism | What it is | Used for |
|---|---|---|
| **Subagents** (`.claude/agents/`) | Separate context + restricted tools; doesn't share the author's reasoning | Roles needing independent judgment: architect, security, reviewer |
| **Skills** (`.claude/skills/`) | Reusable playbooks loaded into the current session | Repeatable procedures, e.g. "add a Lambda endpoint", "add a TF module" |
| **Hooks** (`settings.json`) | Deterministic scripts run by the harness | Always-on rules: `terraform fmt`/`tfsec` after edits, block `.env` writes |
| **CI pipelines** | The real gate | Nothing reaches AWS without passing CI. Agents advise; CI enforces. |

### Roles

| Role | Implementation | Notes |
|---|---|---|
| Architect | Subagent `aws-resume-architect` (read + write docs only) | Produces design docs & ADRs in `docs/architecture/`, which I approve |
| Code generation | Main session + skills | Not a separate agent. I write a good share myself; Claude pairs |
| Security | Subagent (read-only) + `/security-review` + CI scanners | Independent of the code author's context |
| Code review | `/code-review` locally + PR review step in CI | Fits the open-PR-and-stop workflow |

### CI/CD pipelines (GitHub Actions, monorepo path filters)

| Pipeline | Trigger paths | Stages |
|---|---|---|
| `infra.yml` | `aws_resume/infra/**` | fmt → validate → tfsec/checkov → `plan` as PR comment → `apply` on merge (approval required) |
| `backend.yml` | `aws_resume/backend/**` | lint → unit tests → Semgrep → package → deploy Lambda/API (approval required) |
| `frontend.yml` | `aws_resume/frontend/**` | build → test → S3 sync → CloudFront invalidation (approval required) |

Cross-cutting: GitHub **OIDC → IAM role** (no long-lived AWS keys), one
least-privilege role per pipeline, gitleaks secret scanning, branch
protection + required checks on `main`.

---

## Tasks

### Phase 0 — Setup
- [x] Decide AI tooling approach (agents vs skills vs hooks vs CI)
- [x] Create this plan/tracker
- [x] Create architect subagent (`.claude/agents/aws-resume-architect.md`)

### Phase 1 — Architecture
- [x] Run architect agent → draft architecture overview (`docs/architecture/overview.md`)
- [x] Architect drafts ADRs (hosting, IaC tool, backend runtime, data store, domain/DNS, CI auth, remote state) — ADR 0001–0007
- [x] Answer the open questions in `docs/architecture/overview.md` (see "Owner decisions" section)
- [ ] Choose and buy the domain name in Route 53
- [x] Review & approve architecture + ADRs (accepted 2026-10-28)
- [x] Create security subagent (`.claude/agents/aws-resume-security.md`); have it critique the approved design → `docs/security/design-review-2026-10-28.md`
- [ ] Owner decides on security findings SEC-001–SEC-011, then fold the fixes into ADRs/tasks

### Phase 2 — Foundations & infra pipeline
- [ ] Repo layout: `infra/` (+ `infra/bootstrap/`), `backend/`, `frontend/`, `docs/`
- [ ] Bootstrap (manual, local state): budget alert ($5/mo) first — ADR-0007
- [ ] Bootstrap: activate `Project` as a cost allocation tag; create `aws-resume` Resource Group — ADR-0002
- [ ] Terraform remote state (dedicated S3 bucket, `use_lockfile` native locking, Terraform ≥ 1.10) — ADR-0007
- [ ] Per-pipeline IAM roles (infra-plan, infra-apply, backend-deploy, frontend-deploy) reusing the existing GitHub OIDC provider via data source — ADR-0006
- [ ] `aws-resume-boundary` permissions boundary for roles created by infra-apply — ADR-0006
- [ ] GitHub Environments `aws-resume-prod-{infra,backend,frontend}` (main-only; required reviewer on all three) + role ARN repo variables
- [ ] `aws_resume-infra.yml` pipeline (fmt, validate, tfsec/checkov, plan comment, gated apply) — named to match `tf_pr_reviewer-terraform.yml` convention
- [ ] Branch protection + required checks on `main`
- [ ] gitleaks on every PR
- [ ] Hooks: auto `terraform fmt` / `tfsec` on edit
- [ ] (Cross-project follow-up) tighten `tf_pr_reviewer` role trust from `repo:...:*` to environment/event-pinned `sub`

### Phase 3 — Backend
- [ ] Backend infra via Terraform: HTTP API (stage throttling 10/20) + Lambda (placeholder zip, `ignore_changes` on code, `live` alias) + DynamoDB (1 RCU/1 WCU, PITR, deletion protection) — ADR-0003/0004
- [ ] Backend code + unit tests (pytest + moto)
- [ ] `aws_resume-backend.yml` pipeline (lint, test, Semgrep, package, update-function-code → publish-version → update-alias)

### Phase 4 — Frontend
- [ ] (Manual) Buy domain in Route 53, enable auto-renew + transfer lock — ADR-0005 (skip if no custom domain)
- [ ] Frontend infra via Terraform: private S3 + CloudFront OAC + security headers policy + `/api/*` behaviour; import hosted zone; ACM (us-east-1) + alias + CAA records — ADR-0001/0005
- [ ] CloudFront standard logging (v2) → `aws-resume-cf-logs-<account-id>` bucket (private, encrypted, 30-day expiry)
- [ ] Resume site + calls to backend API (relative `/api/visits`, same-origin)
- [ ] `aws_resume-frontend.yml` pipeline (build, test, S3 sync with Cache-Control, invalidation)

### Phase 5 — Hardening & polish
- [ ] Create code-review subagent / CI PR review step
- [ ] Skills for repeated patterns (add as they emerge, not before)
- [ ] Monitoring & alarms (CloudWatch → SNS email: Lambda errors/throttles, API 5xx, DynamoDB throttles, CloudFront 5xx rate; 14-day log retention)
- [ ] Document tfsec/checkov suppressions with cost rationale (no WAF, no CMK, no CloudFront logs)
- [ ] README with architecture diagram + Testing section

---

## Decisions log

| Date | Decision |
|---|---|
| 2026-10-23 | Use subagents for architect/security/review, main session + skills for codegen, CI as the enforcement gate |
| 2026-10-23 | ADR-0001 (proposed): static hosting on private S3 + CloudFront with OAC; WAF deferred |
| 2026-10-23 | ADR-0002 (proposed): Terraform (≥ 1.10) as the IaC tool; bootstrap + main root configs |
| 2026-10-23 | ADR-0003 (proposed): API Gateway HTTP API + Lambda (Python, arm64), routed via CloudFront `/api/*` |
| 2026-10-23 | ADR-0004 (proposed): DynamoDB with provisioned 1 RCU/1 WCU as a cost ceiling |
| 2026-10-23 | ADR-0005 (proposed): custom domain via Route 53 + ACM (us-east-1); domain optional in code |
| 2026-10-23 | ADR-0006 (proposed): OIDC roles pinned to GitHub Environments; separate read-only plan role; permissions boundary |
| 2026-10-23 | ADR-0007 (proposed): dedicated S3 state bucket with native S3 locking (no DynamoDB lock table) |
| 2026-10-28 | Owner answers: custom domain (buy in Route 53), us-east-1, visitor counter only, plain HTML/CSS/JS frontend, same AWS account |
| 2026-10-28 | Naming `aws-resume-*`; tags `Project=aws-resume`, `Environment=prod`, `ManagedBy=terraform`, `Repo`; `Project` activated as a cost allocation tag |
| 2026-10-28 | CloudFront standard logs on → private S3 log bucket, 30-day expiry |
| 2026-10-28 | Required-reviewer approval on all three pipelines; Python for Lambda; CloudFront stays on pay-as-you-go |
| 2026-10-28 | ADRs 0001–0007 accepted. Design security review: proceed with fixes (1 Critical, 3 High, 3 Medium, 3 Low, 1 Info) |
