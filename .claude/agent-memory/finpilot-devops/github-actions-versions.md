---
name: GitHub Actions Pinned SHA Versions
description: All GitHub Action versions pinned to full commit SHAs for security and reproducibility
type: reference
---

All GitHub Actions in FinPilot CI/CD workflows use full commit SHAs (not floating tags like @v4, @v5) for security and reproducibility.

## Actions Used in CI/CD

| Action | SHA | File | Purpose |
|--------|-----|------|---------|
| `actions/checkout` | `11bd71901bbe5b1630ceea73d27597364c9af683` | `.github/workflows/ci.yml`, `deploy-frontend.yml` | Clone repository |
| `actions/setup-python` | `f677139bbe7f9c3f374bc91363276410500c541a` | `.github/workflows/ci.yml` | Setup Python 3.12 |
| `actions/setup-node` | `60edb5dd545a775178fbb3ce9c1ebe5305dfb63c` | `.github/workflows/ci.yml`, `deploy-frontend.yml` | Setup Node.js 20 |
| `pnpm/action-setup` | `v4` | `.github/workflows/ci.yml`, `deploy-frontend.yml` | Setup pnpm 9 |
| `amondnet/vercel-action` | `6aa9de45ca30b7bc9f2c89eecf3ab22c8ba30fdb` | `.github/workflows/deploy-frontend.yml` | Deploy to Vercel |

**Note:** pnpm/action-setup uses `v4` (floating tag) as it's a first-party action that maintains compatibility within major versions.

## How to Update SHAs

When updating an action to a newer version:
1. Check the action's GitHub releases page
2. Copy the full commit SHA from the tag (e.g., from `v4.1.0` tag, get its full SHA)
3. Replace the old SHA in all workflow files
4. Test locally: `act -j <job-name>` (if using act locally)

## Security Rationale

Pinned SHAs prevent:
- Accidental breaking changes from action updates
- Malicious actors from compromising an action tag
- Unexpected behavior changes during CI runs
