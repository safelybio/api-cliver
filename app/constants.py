"""Shared constants for the KYC API."""

# HTTP timeout constants (in seconds)
TIMEOUT_LONG = 120  # LLM prompts with tool calling
TIMEOUT_MEDIUM = 60  # Extraction calls
TIMEOUT_SHORT = 30  # External APIs (EPMC, ORCID, screening list)

# Text truncation limits
TOOL_CONTEXT_TRUNCATION = 2000  # Max chars for tool context in extraction prompts
SNIPPET_PREVIEW_LENGTH = 200  # Max chars for snippet previews
