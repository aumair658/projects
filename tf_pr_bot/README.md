# tf_pr_bot

A standalone Terraform PR-review bot: a GitHub App backed by an AWS Lambda
Function URL. On every `pull_request` event it pulls the changed `.tf`
files at the PR head, runs [tfsec](https://github.com/aquasecurity/tfsec)
against them, and posts the findings as a PR comment.

This is the real reviewer `tf_pr_reviewer/` was built to be scanned by -
point this bot at that repo (or any repo) and it'll flag the two
intentional findings in `tf_pr_reviewer/s3.tf` and
`tf_pr_reviewer/security_group.tf` on a PR that touches them.

## Architecture

```
GitHub PR event -> GitHub App webhook -> Lambda Function URL
                                             |
                                             v
                              verify HMAC signature (webhook secret)
                                             |
                                             v
                    mint App JWT -> exchange for installation token
                                             |
                                             v
                       fetch changed *.tf files at PR head SHA
                                             |
                                             v
                     run tfsec (bundled as a Lambda layer)
                                             |
                                             v
                        POST findings as a PR comment
```

Everything here is free at this scale: Lambda's free tier (1M requests +
400k GB-s/month) comfortably covers a personal PR bot, Function URLs have
no extra cost beyond the Lambda invocation, and SSM Parameter Store
(Standard tier) is free - deliberately used instead of Secrets Manager,
which charges per secret.

**Known trade-off:** GitHub enforces a hard 10s timeout on webhook
responses. This handler runs synchronously (verify -> fetch -> scan ->
comment) inside that window, which is fine for a small diff but wouldn't
scale to a large monorepo PR. A production version would ack immediately
and hand off to a second Lambda (via SQS) to do the actual review.

## One-time setup

### 1. Register the GitHub App

Go to **github.com/settings/apps/new** (or your org's equivalent) and
create an app with:

- **Webhook URL**: leave blank for now - you'll fill this in after the
  first `terraform apply` gives you the Function URL.
- **Webhook secret**: generate one yourself (e.g. `openssl rand -hex 32`)
  and remember it - you'll store it in SSM in step 3.
- **Permissions**: Repository -> Pull requests: **Read and write**,
  Repository -> Contents: **Read-only**. (Metadata read-only is included
  automatically.)
- **Subscribe to events**: Pull request.
- Install it on `aumair658/projects` (or whichever repo you want
  reviewed) once it's created.

After creating the app, note its **App ID** (top of the settings page)
and generate + download a **private key** (`.pem`) from the same page.

### 2. Deploy the infrastructure

```bash
cd tf_pr_bot
scripts/build_lambda.sh
scripts/build_layer.sh
terraform init
terraform apply -var="github_app_id=<your App ID>"
```

### 3. Populate the real secrets

Terraform creates the SSM parameters with placeholder values on purpose -
the real values shouldn't live in Terraform state. Set them for real:

```bash
aws ssm put-parameter \
  --name "$(terraform output -raw private_key_parameter_name)" \
  --type SecureString --overwrite \
  --value "$(cat /path/to/downloaded-private-key.pem)"

aws ssm put-parameter \
  --name "$(terraform output -raw webhook_secret_parameter_name)" \
  --type SecureString --overwrite \
  --value "<the webhook secret you generated in step 1>"
```

### 4. Wire up the webhook URL

```bash
terraform output webhook_url
```

Paste that into the GitHub App's **Webhook URL** field and save.

## Trying it

Open a PR against a repo the app is installed on that touches a `.tf`
file - e.g. a PR against `tf_pr_reviewer/s3.tf` in this monorepo. Within
a few seconds you should see a comment from the bot listing tfsec's
findings (or a clean-scan confirmation if there aren't any).

## Local development

```bash
cd tf_pr_bot
scripts/build_lambda.sh
scripts/build_layer.sh
terraform init
terraform validate
```

The build artifacts (`build/lambda.zip`, `build/layer/tfsec-layer.zip`)
have to exist before `validate` - both `aws_lambda_function` and
`aws_lambda_layer_version` hash the zip contents at plan time, so a
missing file is a hard error, not just a warning. `plan`/`apply`
additionally need AWS credentials for the same account `tf_pr_reviewer`
uses.
