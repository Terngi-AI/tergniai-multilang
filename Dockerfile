# Pinned by digest (the multi-arch manifest list), so every build uses the exact same
# base image. Bump the tag+digest together, as described in CONTRIBUTING.md.
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set the working directory in the container
WORKDIR /app

# Copy only the lockfile first to leverage Docker's caching mechanism
COPY requirements.lock ./

# Install exact, hash-verified dependencies: a tampered package on PyPI fails the build
RUN pip install --require-hashes --no-deps -r requirements.lock

# Copy the rest of the application code
COPY . .

# Run as an unprivileged user
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

# Expose the application port
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

# Command to run the application (no --reload in production).
# Only proxies listed in FORWARDED_ALLOW_IPS may set X-Forwarded-For; the default trusts
# loopback only, so direct clients cannot spoof their address.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1,::1}\""]
