# Contributing to Terngi AI

Thanks for helping! This guide explains how to propose changes.

## Ground rules

- Be kind and follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Never commit secrets.** Keys belong in `.env` (git-ignored) or in GitHub Actions secrets.
  CI runs a secret scanner and will fail if it finds one.
- Report security vulnerabilities privately (see [SECURITY.md](SECURITY.md)), not in issues.

## Ways to contribute

- Report bugs or request features through [GitHub Issues](../../issues) using the templates.
- Improve translations or prompts for Yoruba, Hausa and Igbo — native-speaker review is especially valuable.
- Add support for another language.
- Improve docs and tests.

For larger changes, open an issue first so we can agree on the approach before you write code.

## Development setup

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<you>/tergniai-multilang.git
cd tergniai-multilang

# 2. Create a virtual environment (Python 3.11+)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies and git hooks
pip install --require-hashes -r requirements-dev.lock
pre-commit install

# 4. Configure keys (only needed to call the real services)
cp .env.example .env

# 5. Run the API
uvicorn main:app --reload
```

The test suite mocks Azure and Groq, so **you do not need API keys to run tests**.

## Branches

| Branch | Purpose |
|---|---|
| `main` | Stable, released code. Only updated by release PRs from `develop`. |
| `develop` | Integration branch. **Open your pull requests against `develop`.** |
| `feat/…`, `fix/…`, `docs/…`, `chore/…` | Your work, branched from `develop`. |

Both `main` and `develop` are protected: changes go through pull requests, CI must pass, and a
maintainer must approve.

## Making a change

1. Create a branch from `develop`: `git checkout develop && git pull && git checkout -b fix/short-description`.
2. Make your change, keeping it focused on one thing.
3. Add or update tests in `tests/`.
4. Run the checks:

   ```bash
   ruff check . && ruff format --check .
   mypy .
   pytest --cov
   ```

5. Commit using clear messages. We follow [Conventional Commits](https://www.conventionalcommits.org/)
   (e.g. `feat: add Pidgin support`, `fix: handle empty Azure response`).
6. Push and open a pull request against `develop`, filling in the PR template.

> `main` and `develop` are protected: every change goes through a pull request, all CI checks must
> pass, and a maintainer must approve the PR before it can be merged. For first-time
> contributors, a maintainer also approves the CI run before it starts.

## Pull request checklist

- CI is green (lint, types, tests on Python 3.11–3.13, Docker build, security scans).
- Coverage stays at or above 85%.
- New behaviour is documented in `README.md`.
- No secrets, `.env` files or large binaries are committed.
- The Security workflow passes (malware, code, dependency, container and attack scans).

A maintainer will review your PR. We may ask for changes — that is a normal part of the process.

## Code style

- Formatting and linting: [Ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`).
- Type hints on public functions; `mypy .` must pass.
- Network calls must be async and have a timeout.
- Do not return raw upstream error messages to clients; log them instead.

## Security checks and dependencies

Besides CI, the [Security workflow](.github/workflows/security.yml) runs on every PR: an antivirus
scan (ClamAV), static analysis (Semgrep), dependency audits (pip-audit, OSV-Scanner), a container
scan (Trivy) and an attack simulation against the API (OWASP ZAP). If one fails, open the job log
to see why; ask in the PR if you think it's a false positive.

This project doesn't use Dependabot, so dependencies are updated by hand:

- **Python packages:** every package, including indirect ones, is locked to an exact version
  with checksums in `requirements.lock` (used by Docker) and `requirements-dev.lock` (used by CI).
  After changing `requirements*.txt`, or to pick up security fixes, regenerate both and audit them:

  ```bash
  uv pip compile requirements.txt --universal --python-version 3.11 --generate-hashes -o requirements.lock
  uv pip compile requirements-dev.txt --universal --python-version 3.11 --generate-hashes -o requirements-dev.lock
  pip-audit --strict --require-hashes --disable-pip -r requirements-dev.lock
  ```

  Add `--upgrade` to the compile commands to move everything to the latest compatible versions.
- **GitHub Actions:** actions are pinned to a full commit SHA with the version in a comment, e.g.
  `actions/checkout@<sha> # v4.4.0`. To update one, look up the new release's commit
  (`gh api repos/actions/checkout/commits/v4.5.0 --jq .sha`) and replace both the SHA and the comment.
- **Scanner versions** are set at the top of `security.yml`.

## Adding a language

1. Check the language is supported by [Azure Translator](https://learn.microsoft.com/azure/ai-services/translator/language-support).
2. Add its code to `SUPPORTED_LANGUAGES` in `config.py`.
3. Update the tests and the README.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
