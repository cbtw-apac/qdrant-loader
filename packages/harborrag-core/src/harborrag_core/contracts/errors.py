class HarborError(Exception):
    """Base HarborRAG error."""


class HarborConfigurationError(HarborError):
    """Configuration is invalid."""


class HarborCapabilityError(HarborError):
    """Requested capability is not supported."""


class HarborSecurityError(HarborError):
    """Security policy rejected an operation."""


class HarborDeadlineExceeded(HarborError):
    """Operation exceeded its deadline."""
