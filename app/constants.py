"""Shared constants for the KYC API."""

# HTTP timeout constants (in seconds)
TIMEOUT_LONG = 120  # LLM prompts with tool calling
TIMEOUT_MEDIUM = 60  # Extraction calls
TIMEOUT_SHORT = 30  # External APIs (EPMC, ORCID, screening list)

# Text truncation limits
TOOL_CONTEXT_TRUNCATION = 2000  # Max chars for tool context in extraction prompts
SNIPPET_PREVIEW_LENGTH = 200  # Max chars for snippet previews

# Max completion tokens for the verification tool-calling loop. OpenRouter
# reserves this budget up front against the account balance, so an unbounded
# request can 402 on low-balance accounts; this keeps the reservation sane
# while leaving ample room for a verification write-up.
MAX_COMPLETION_TOKENS = 8000
