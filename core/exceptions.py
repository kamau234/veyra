"""VEYRA error hierarchy.

Every error surfaced to the user is one of these; the UI translates them into
inline field errors, dialogs or import reports. Python tracebacks are never
shown to the user — technical detail goes to the log instead.
"""


class VeyraError(Exception):
    """Base class for all expected application errors."""

    #: Default human-readable message used when none is supplied.
    default_message = "Something went wrong."

    def __init__(self, message: str | None = None, *, detail: str | None = None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.detail = detail


class ValidationError(VeyraError):
    """A user input rule was broken (e.g. negative selling price)."""

    default_message = "Please correct the highlighted fields."

    def __init__(self, message=None, *, field: str | None = None, detail=None):
        super().__init__(message, detail=detail)
        self.field = field


class BusinessRuleError(VeyraError):
    """A domain rule was broken (e.g. quantity exceeds available stock)."""

    default_message = "This action is not allowed by VEYRA's business rules."


class FileError(VeyraError):
    """A file could not be read or written (workbook, image, export)."""

    default_message = "The file could not be processed."


class ImageError(FileError):
    """An image was unsupported, corrupt or unreadable."""

    default_message = "That image could not be used."


class DatabaseError(VeyraError):
    """A persistence failure occurred; the transaction was rolled back."""

    default_message = "VEYRA could not save to the database. Nothing was changed."


class ImportRowError:
    """One cell-level problem found while validating an import workbook."""

    __slots__ = ("row", "column", "message")

    def __init__(self, row: int, column: str, message: str):
        self.row = row
        self.column = column
        self.message = message

    def __str__(self) -> str:
        return f"Row {self.row} - {self.column}: {self.message}"

    def __repr__(self) -> str:
        return f"ImportRowError(row={self.row}, column={self.column!r}, message={self.message!r})"
