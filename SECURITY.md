# Security Policy

## Supported versions

Security fixes are applied to the latest release on the `main` branch.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report vulnerabilities privately using GitHub's
[private vulnerability reporting](../../security/advisories/new)
(Security tab → "Report a vulnerability").

Please include:

- A description of the issue and its impact
- Steps to reproduce or a proof of concept
- Any suggested fix

We aim to acknowledge reports within 3 working days and to share a fix timeline within 10 working days.

## Handling secrets

- API keys are read only from environment variables. Never commit them.
- If you accidentally commit a key, **revoke it immediately** at the provider (Azure portal / Groq console);
  removing it from git history is not enough.
- CI scans every push and pull request for secrets with gitleaks, and GitHub secret scanning
  with push protection blocks most keys before they're even pushed.

## Automated security scanning

Every pull request, every push to `main`/`develop`, and a daily scheduled run go through
these checks ([`security.yml`](.github/workflows/security.yml) and
[`ci.yml`](.github/workflows/ci.yml)):

| Threat | Check | Tool |
|---|---|---|
| Viruses and malware added to the repo (including in git history) | Antivirus scan of every file | [ClamAV](https://www.clamav.net/) |
| Leaked keys and tokens | Secret scan of the full history | [gitleaks](https://github.com/gitleaks/gitleaks), GitHub secret scanning |
| Insecure code (injection, unsafe deserialisation, weak crypto, ...) | Static analysis of Python, the Dockerfile and workflows | [Semgrep](https://semgrep.dev/), Ruff's Bandit rules (`S`) |
| Vulnerable dependencies | Checked against the PyPA and OSV advisory databases, daily | [pip-audit](https://github.com/pypa/pip-audit), [OSV-Scanner](https://github.com/google/osv-scanner) |
| Vulnerable OS packages or a misconfigured container | Image and Dockerfile scan | [Trivy](https://trivy.dev/) |
| Attacks against the running API | Active scan of every endpoint (injection, header and error-handling checks) | [OWASP ZAP](https://www.zaproxy.org/) |
| Supply-chain weaknesses in the project itself | Branch protection, pinned dependencies, dangerous workflow patterns | [OpenSSF Scorecard](https://scorecard.dev/) |

Supply-chain hardening:

- Every Python package, including indirect dependencies, is locked to an exact version and
  checksum (`requirements.lock`, `requirements-dev.lock`). Docker and CI install with
  `--require-hashes`, so a tampered package on PyPI fails the build instead of being installed.
- Every GitHub Action is pinned to a full commit SHA, so a moved or hijacked tag can't run in CI.
  Scanner images and tools are pinned to exact versions.
- Workflows run with a read-only `GITHUB_TOKEN`, don't keep it in `.git/config`, and use
  `pull_request` (never `pull_request_target`). Workflows from first-time and external
  contributors need a maintainer's approval before they run.
- Dependabot is not used. Dependency vulnerabilities are caught by the daily scan instead, and
  maintainers update versions and action pins by hand (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Runtime protections

- Optional API-key authentication; keys are compared in constant time and never logged.
- Per-client rate limiting. Only valid API keys count as a separate client, so made-up keys can't
  be used to dodge the limit.
- Request bodies larger than `MAX_REQUEST_BYTES` (1 MiB by default) are rejected with `413`,
  including streamed bodies without a `Content-Length`.
- Security headers on every response: `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, a strict `Content-Security-Policy`, and HSTS over HTTPS.
- Redis (optional) should never be reachable from the internet: keep it on a private network
  (as in `docker-compose.yml`) and use a password or TLS (`rediss://user:pass@host`) in
  `REDIS_URL` when it isn't local. API keys are stored only as hashes in Redis keys and
  conversation owners.
- Upstream error details are logged, never returned to clients. Since providers can echo the
  user's text in error messages, `INFO`/`WARNING` logs carry only the status, the provider's
  error code and the request ID; the (truncated) body is logged at `DEBUG` only.
  Conversation history can't inject system prompts.
- User text is sent to third-party AI providers that act as data processors. What each
  provider receives and its retention and training terms are documented in
  [docs/DATA.md](docs/DATA.md), which must be reviewed whenever a provider is added.

## For operators

Before exposing the API to the internet, work through the threat model and the operator
checklist in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md): assets, threats and
mitigations, and the settings to check before first startup and on a regular basis.
