class AO3Error(Exception):
    """Base exception for ao3-py."""


class AO3ParseError(AO3Error):
    """AO3 HTML did not contain the structure required by a parser."""


class AO3AuthenticationError(AO3Error):
    """The requested resource requires an authenticated AO3 session."""


class AO3ActionError(AO3Error):
    """AO3 rejected or does not support a requested write operation."""


class AO3InvalidURLError(AO3Error, ValueError):
    """A URL does not identify a supported AO3 resource."""
