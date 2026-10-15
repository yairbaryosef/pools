from __future__ import annotations


class ApplicationError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

class AuthenticationRequired(ApplicationError):
    def __init__(self) -> None:
        super().__init__("AUTHENTICATION_REQUIRED", "Authentication is required", 401)


class AuthenticationFailed(ApplicationError):
    def __init__(self) -> None:
        super().__init__("AUTHENTICATION_FAILED", "Invalid username or password", 401)


class PersistenceContractError(ApplicationError):
    def __init__(self, capability: str) -> None:
        super().__init__(
            "INTERNAL_ERROR", f"Persistence capability is unavailable: {capability}", 500
        )
