---
name: aws-sso-login
description: Restore AWS CLI authentication for an existing IAM Identity Center profile when its SSO session is missing or expired.
---

# AWS SSO login

Use this when an AWS CLI task needs an existing IAM Identity Center profile and
its session may have expired.

1. Use the same profile as the intended AWS command. Respect an explicit
   `--profile`; otherwise use the CLI's current profile selection. Do not
   change AWS configuration or choose a different account or role.
2. Check authentication with
   `aws sts get-caller-identity --query Account --output text >/dev/null`
   using that profile. If it succeeds, continue without logging in.
3. If the check fails, inspect the error. Run `aws sso login` with the same
   profile only when it uses IAM Identity Center and the error indicates
   missing or expired SSO authentication. Let the user complete browser
   sign-in; never handle passwords, MFA codes, or cached tokens.
4. Repeat the identity check once, then continue the original command if it
   succeeds. If login or the check still fails, report the error and stop.
   Do not treat permission, network, region, or profile configuration errors
   as a reason to log in.

For a named profile, append `--profile PROFILE` to both the identity check and
`aws sso login`. For the active default profile, omit it. Do not print
credential files, SSO cache contents, or token-bearing URLs.
