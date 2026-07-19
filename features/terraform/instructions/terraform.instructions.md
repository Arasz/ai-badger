---
description: 'Terraform conventions and validation.'
applyTo: '**/*.tf,**/*.tfvars,**/*.tftest.hcl,**/*.hcl'
---

# Terraform

- Keep secrets out of Terraform files, committed variable files, outputs, logs, and examples. Use your cloud provider's secret-manager references and sensitive variables as documented in the Terraform root's `README.md`.
- Tag resources and preserve the documented cost, authentication, and resilience decisions unless the relevant specification is updated in the same change.
- Preserve any documented service-decoupling and authentication-gateway posture unless the relevant docs and ADRs are updated in the same change.
- Keep every partitioned datastore container/table partitioned by its tenant/owner key; do not weaken authorization or network controls for convenience.
- Add or update a failing `tests/*.tftest.hcl` assertion in the Terraform root before changing Terraform behavior.
- From the Terraform root (e.g. `infra/` or `infrastructure/`), run `terraform fmt -check -recursive`, `terraform init -backend=false -input=false`, `terraform validate`, and `terraform test`.
- Never use `-target`. Do not run `terraform apply` unless the user explicitly requests it and the documented remote backend is configured.
