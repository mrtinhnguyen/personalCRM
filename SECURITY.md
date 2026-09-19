# Security policy

This is a single-user personal CRM that can store sensitive relationship and
message archives. The current main branch receives fixes on a best-effort basis;
there is no supported enterprise release or independent security audit.

## Report a vulnerability privately

Use GitHub's **Security → Advisories → Report a vulnerability** at
<https://github.com/hmumixaM/monica-next/security/advisories/new>.
Do not include production records, credentials, or complete database dumps.
Provide a minimal synthetic reproduction, the affected revision, and the impact.
If private reporting is unavailable, open a public issue requesting a private
contact channel **without including vulnerability details**.

## Operating boundaries

- Initialize the administrator locally before exposing the installation.
- Use unique generated secrets, trusted HTTPS, `APP_ENV=production`, and a VPN or
  controlled reverse proxy. Default HTTP settings are for loopback development.
- Protect database volumes, raw archives, media, backups, `.env`, and TLS keys.
  Self-hosting does not encrypt those files automatically.
- Grant collectors only the source tokens and import secrets they require.
  Revoke tokens and sessions when devices or collectors are retired.
- Keep dependency updates, backups, and restore rehearsals part of operations.
- TOTP and session controls are implemented; WebAuthn/passkey schema placeholders
  must not be interpreted as a complete passkey login feature.
- Maps request public OpenStreetMap tiles. Remote media import can contact
  source-platform CDNs. Review these external requests for your environment.
- The synthetic showcase is for interface evaluation, with no production API or
  account access. Do not repurpose it to host sensitive data.

## Public repository policy

Only code, generic examples, and independently constructed demo data belong here.
Personal names in contact records, chat archives, social account identifiers,
private hostnames, credentials, and private acceptance-test histories do not.
Review screenshots as well as text files; blur alone is not sufficient.
Third-party author attribution and public library license notices are preserved.
