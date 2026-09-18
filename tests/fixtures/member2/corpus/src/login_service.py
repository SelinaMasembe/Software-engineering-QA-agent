"""Synthetic authentication service used as retrieval fixture input."""

from dataclasses import dataclass

MAX_FAILED_ATTEMPTS = 5


@dataclass(frozen=True)
class AuthenticationResult:
    authenticated: bool
    reason: str


class LoginService:
    def __init__(self) -> None:
        self._failures: dict[str, int] = {}

    def authenticate(
        self,
        username: str,
        password: str,
        service_available: bool = True,
    ) -> AuthenticationResult:
        if not service_available:
            return AuthenticationResult(False, "service_unavailable")
        if self.is_locked(username):
            return AuthenticationResult(False, "account_locked")
        if password != "correct-password":
            self._failures[username] = self._failures.get(username, 0) + 1
            return AuthenticationResult(False, "invalid_credentials")
        self._failures[username] = 0
        return AuthenticationResult(True, "authenticated")

    def is_locked(self, username: str) -> bool:
        return self._failures.get(username, 0) >= MAX_FAILED_ATTEMPTS
