"""Cloudflare Access authentication and hosted HTTP security policy."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import PyJWKClient

from kz_tax_report.config import get_hosted_configuration


_subject: ContextVar[str | None] = ContextVar("authenticated_subject", default=None)


class AuthenticationError(ValueError):
    """Raised when a Cloudflare Access token is missing or invalid."""


@dataclass
class AccessTokenVerifier:
    issuer: str
    audience: str
    jwks_url: str

    def __post_init__(self) -> None:
        self._keys = PyJWKClient(self.jwks_url)

    def verify(self, token: str) -> str:
        if not token:
            raise AuthenticationError("Authentication required")
        try:
            signing_key = self._keys.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, OSError) as error:
            raise AuthenticationError("Invalid authentication token") from error
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("Authentication subject is missing")
        return subject


def get_authenticated_subject() -> str | None:
    return _subject.get()


def install_hosted_security(app: Any) -> None:
    """Install auth and headers on the NiceGUI FastAPI application."""

    settings = get_hosted_configuration()
    verifier = AccessTokenVerifier(
        str(settings["issuer"]), str(settings["audience"]), str(settings["jwks_url"])
    )

    @app.middleware("http")
    async def hosted_security(request: Request, call_next: Any) -> Any:
        if request.url.path == "/healthz":
            response = await call_next(request)
            return _add_security_headers(response)
        if request.headers.get("x-forwarded-proto", request.url.scheme) != "https":
            return JSONResponse({"detail": "HTTPS is required"}, status_code=400)
        token = _extract_token(request)
        try:
            subject = verifier.verify(token)
        except AuthenticationError:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        token_handle = _subject.set(subject)
        try:
            response = await call_next(request)
        finally:
            _subject.reset(token_handle)
        return _add_security_headers(response)


def _extract_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get("CF_Authorization", "")


def _add_security_headers(response: Any) -> Any:
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' https:; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response
