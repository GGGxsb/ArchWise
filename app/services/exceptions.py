class RequirementParsingError(RuntimeError):
    """Raised when DeepSeek cannot provide a valid structured requirement parse."""


class DeepSeekServiceError(RuntimeError):
    """Raised when a required DeepSeek Agent call is unavailable or invalid."""
