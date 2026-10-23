# 0005. Domain and DNS: Route 53 + ACM, custom domain
Status: Proposed
Date: 2026-10-23

## Context

A resume site is more credible on a custom domain, and DNS, TLS and
certificate validation are core AWS skills. The owner hasn't said whether
they want a custom domain or already own one. **Assumption:** yes, a new
domain bought through Route 53. The design must also work with no domain at
all so the earlier phases aren't blocked on the purchase.

## Options considered

### A. Register the domain in Route 53, with a Route 53 hosted zone and ACM cert
- **Pros:** Everything in one account and one Terraform provider. Route 53
  auto-creates the hosted zone and sets its NS records at the registrar.
  ACM DNS validation is fully automated in Terraform
  (`aws_acm_certificate` + `aws_route53_record` + `aws_acm_certificate_validation`).
  Alias A/AAAA records to CloudFront are **free** to query.
- **Cons:** The hosted zone bills $0.50/month while idle. Registration is a
  purchase, so it's a manual bootstrap step, not CI. The auto-created zone
  then has to be **imported** into Terraform.
- **Rough cost:** $0.50/month zone + about $15/year for .com (price varies by TLD).

### B. Domain at an external registrar (for example Cloudflare or Namecheap), DNS delegated to Route 53
- **Pros:** Possibly cheaper registration. Keeps an existing domain.
- **Cons:** One manual step outside AWS (setting four NS records at the
  registrar). DNS still costs $0.50/month for the zone.
- **Rough cost:** Same zone cost plus the registrar's price.

### C. External DNS (for example Cloudflare DNS), no Route 53
- **Pros:** Free DNS. Cloudflare also offers free proxying and WAF.
- **Cons:** A second provider in Terraform, plus a second API token, which
  is a **secret** the infra pipeline would need. CNAME at the zone apex
  needs flattening. Less AWS learning.
- **Rough cost:** About $0 for DNS plus registration.

### D. No custom domain, just the `dxxxx.cloudfront.net` URL
- **Pros:** $0, no DNS or ACM to manage, no secrets.
- **Cons:** Looks unprofessional on a resume. Skips the DNS/TLS learning.
- **Rough cost:** $0.

## Decision

**Option A** by default, or **Option B** if the owner already owns a domain.
Design the Terraform so the domain is optional (`var.domain_name`, empty
means Option D) and the stack works on the CloudFront default URL until the
domain exists.

- **Manual bootstrap:** buy the domain in the Route 53 console (it's a
  financial transaction, so a human does it), turn on auto-renew and
  registrar transfer lock.
- **Terraform (infra pipeline):** import the auto-created hosted zone with
  an `import` block, then manage:
  - the ACM certificate in **us-east-1** for `example.com` and `www.example.com`,
    with DNS validation records
  - alias A and AAAA records for apex and `www` → CloudFront. Redirect `www`
    to apex, or serve both. Serving both is simplest: two aliases on the
    distribution.
  - **CAA** records allowing only `amazon.com` (and `amazontrust.com`) to
    issue certificates for the domain
- **DNSSEC: deferred.** It needs a customer-managed asymmetric KMS key
  ($1/month while idle) and careful key rollover. Good later exercise.

## Consequences

- **Security:** ACM handles the private key, so there's no key material
  anywhere in the repo or state. CAA records limit who can issue certs.
  Registrar lock and auto-renew prevent domain hijack or expiry. Dangling
  DNS risk: when tearing down, delete records before (or with) the
  CloudFront distribution so the alias never points at a released
  distribution. Terraform handles this order if both are in the same state.
- **Cost:** $0.50/month (zone) + domain. These are the only idle charges in
  the design.
- **Infra pipeline:** the apply role needs `route53:ChangeResourceRecordSets`,
  `GetHostedZone`, `ListResourceRecordSets` and `GetChange` on **this zone ID
  only**, plus `acm:*Certificate*` actions in us-east-1. No
  `route53domains:*` permissions, because CI never touches registration.
- **Backend/frontend pipelines:** unaffected.

Sources: [Route 53 pricing](https://aws.amazon.com/route53/pricing/) ($0.50/zone/month, alias queries to CloudFront free).
