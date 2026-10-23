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
| `infra.yml` | `aws_resume/infra/**` | fmt → validate → tfsec/checkov → `plan` as PR comment → `apply` on merge (manual approval env) |
| `backend.yml` | `aws_resume/backend/**` | lint → unit tests → Semgrep → package → deploy Lambda/API |
| `frontend.yml` | `aws_resume/frontend/**` | build → test → S3 sync → CloudFront invalidation |

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
- [ ] Run architect agent → draft architecture overview (`docs/architecture/overview.md`)
- [ ] Architect drafts ADRs (hosting, IaC tool, backend runtime, data store, domain/DNS, CI auth)
- [ ] Review & approve architecture + ADRs
- [ ] Create security subagent; have it critique the approved design

### Phase 2 — Foundations & infra pipeline
- [ ] Repo layout: `infra/`, `backend/`, `frontend/`, `docs/`
- [ ] Terraform remote state (S3 + locking)
- [ ] GitHub OIDC provider + per-pipeline IAM roles
- [ ] `infra.yml` pipeline (fmt, validate, tfsec/checkov, plan comment, gated apply)
- [ ] Branch protection + required checks on `main`
- [ ] Hooks: auto `terraform fmt` / `tfsec` on edit

### Phase 3 — Backend
- [ ] Backend infra (API Gateway, Lambda, data store) via Terraform
- [ ] Backend code + unit tests
- [ ] `backend.yml` pipeline (lint, test, Semgrep, package, deploy)

### Phase 4 — Frontend
- [ ] Frontend infra (S3, CloudFront, ACM, Route 53) via Terraform
- [ ] Resume site + calls to backend API
- [ ] `frontend.yml` pipeline (build, test, S3 sync, invalidation)

### Phase 5 — Hardening & polish
- [ ] Create code-review subagent / CI PR review step
- [ ] Skills for repeated patterns (add as they emerge, not before)
- [ ] Monitoring & alarms (CloudWatch, budget alert)
- [ ] README with architecture diagram + Testing section

---

## Decisions log

| Date | Decision |
|---|---|
| 2026-10-23 | Use subagents for architect/security/review, main session + skills for codegen, CI as the enforcement gate |
