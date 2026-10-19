"""
Configuration settings for the Terngi Translation API

Secrets are read from environment variables (or a local `.env` file).
Never hardcode API keys in this file.
"""

import os

from dotenv import load_dotenv

# Load variables from a local .env file if present (no-op in production)
load_dotenv()

# Define supported languages
SUPPORTED_LANGUAGES = {"en": "English", "yo": "Yoruba", "ha": "Hausa", "ig": "Igbo"}

# Azure Translator configuration
AZURE_TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY", "")
AZURE_TRANSLATOR_ENDPOINT = os.getenv(
    "AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com"
)
AZURE_TRANSLATOR_LOCATION = os.getenv("AZURE_TRANSLATOR_LOCATION", "global")

# Which service translates and detects languages:
#   "auto"  - Azure when configured, falling back to Groq if Azure is missing or fails
#   "azure" - Azure only
#   "groq"  - Groq LLM only
TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "auto").strip().lower()

# Groq configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Timeout (seconds) for calls to upstream services
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))

# Retries for upstream 429/5xx responses and connection errors (0 disables).
# Backoff is exponential with full jitter; a Retry-After header is honoured.
UPSTREAM_MAX_RETRIES = int(os.getenv("UPSTREAM_MAX_RETRIES", "2"))
UPSTREAM_RETRY_BASE_DELAY = float(os.getenv("UPSTREAM_RETRY_BASE_DELAY", "0.5"))
# Longest single wait (seconds). A Retry-After above this fails fast instead.
UPSTREAM_RETRY_MAX_DELAY = float(os.getenv("UPSTREAM_RETRY_MAX_DELAY", "10"))

# Request limits
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", "5000"))
MAX_MEMORY_MESSAGES = int(os.getenv("MAX_MEMORY_MESSAGES", "20"))

# Batch translation limits (Azure allows at most 50,000 characters per request)
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "25"))
MAX_BATCH_CHARACTERS = int(os.getenv("MAX_BATCH_CHARACTERS", "50000"))

# Translation cache (set CACHE_TTL_SECONDS=0 to disable)
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
CACHE_MAX_ITEMS = int(os.getenv("CACHE_MAX_ITEMS", "1000"))

# Client authentication: comma-separated keys accepted in the X-API-Key header.
# Leave empty to disable authentication (e.g. for local development).
API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]

# Requests per minute allowed per client (API key or IP). 0 disables rate limiting.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

# Comma-separated list of allowed CORS origins (empty disables CORS)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

# Groq system prompt
GROQ_SYSTEM_PROMPT = """You are Terngi AI, a helpful, culturally aware assistant that specializes in multilingual conversations.
If asked who you are, say you are Terngi AI; do not claim to be any other assistant.
Your responses should be clear, natural, and conversational.
If the user provides context from previous conversations, use it to give more relevant and personalized responses.
Keep your responses informative but concise.
Respond only in English - your response will be translated if needed.
"""
