from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticationResult:
    authenticated: bool
    reason: str


def authenticate(password: str, service_available: bool = True) -> AuthenticationResult:
    if not service_available:
        return AuthenticationResult(False, "service_unavailable")
    if password != "correct-password":
        return AuthenticationResult(False, "invalid_credentials")
    return AuthenticationResult(True, "authenticated")
