"""Errors the core raises for problems the user can fix."""


class ExchangeError(Exception):
    """Base class for user-facing errors."""


class DefinitionError(ExchangeError):
    """An environment or dossier-type definition file is invalid."""

    def __init__(self, source: object, message: str) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source


class LibraryError(ExchangeError):
    """The library database cannot be opened or migrated."""


class ScanError(ExchangeError):
    """A scan cannot start (bad folder, unsafe database location, ...)."""
