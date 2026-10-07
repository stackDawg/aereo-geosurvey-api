"""Errors raised by the service layer, each mapped to an HTTP status by ``app.main``."""


class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UnauthorizedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    """The resource is not in a state that allows the request (e.g. still processing)."""

    status_code = 409


class FileTooLargeError(AppError):
    status_code = 413


class UnsupportedFileTypeError(AppError):
    status_code = 415


class InvalidUploadError(AppError):
    status_code = 422


class InvalidRequestError(AppError):
    status_code = 422


class ServiceUnavailableError(AppError):
    status_code = 503
