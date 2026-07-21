from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from kz_tax_report.config import get_hosted_configuration
from kz_tax_report.hosted_security import AccessTokenVerifier, AuthenticationError


@pytest.fixture
def hosted_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "KZ_TAX_REPORT_MODE": "hosted",
        "KZ_TAX_REPORT_ACCESS_ISSUER": "https://tenant.cloudflareaccess.com",
        "KZ_TAX_REPORT_ACCESS_AUDIENCE": "app-audience",
        "KZ_TAX_REPORT_ACCESS_JWKS_URL": "https://tenant.cloudflareaccess.com/cdn-cgi/access/certs",
        "KZ_TAX_REPORT_SESSION_SECRET": "s" * 32,
        "KZ_TAX_REPORT_PUBLIC_URL": "https://tax.example.test",
        "KZ_TAX_REPORT_TRUST_PROXY": "true",
        "KZ_TAX_REPORT_ARTIFACT_TTL_SECONDS": "3600",
        "KZ_TAX_REPORT_MAX_UPLOAD_BYTES": "1024",
        "KZ_TAX_REPORT_MAX_JOB_BYTES": "2048",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_hosted_configuration_requires_all_security_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KZ_TAX_REPORT_MODE", "hosted")

    with pytest.raises(ValueError, match="ACCESS_ISSUER"):
        get_hosted_configuration()


def test_hosted_configuration_requires_explicit_limits(
    hosted_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KZ_TAX_REPORT_MAX_JOB_BYTES")

    with pytest.raises(ValueError, match="MAX_JOB_BYTES"):
        get_hosted_configuration()


def test_access_token_requires_signature_and_expected_claims() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    verifier = AccessTokenVerifier(
        "https://tenant.cloudflareaccess.com",
        "app-audience",
        "https://jwks.example.test/certs",
    )
    verifier._keys.get_signing_key_from_jwt = lambda token: type(
        "SigningKey", (), {"key": public_key}
    )()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "https://tenant.cloudflareaccess.com",
            "aud": "app-audience",
            "sub": "invitee-a",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    assert verifier.verify(token) == "invitee-a"

    with pytest.raises(AuthenticationError, match="Invalid"):
        verifier.verify(token + "tampered")


def test_access_token_rejects_wrong_audience() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AccessTokenVerifier(
        "https://tenant.cloudflareaccess.com",
        "app-audience",
        "https://jwks.example.test/certs",
    )
    verifier._keys.get_signing_key_from_jwt = lambda token: type(
        "SigningKey", (), {"key": private_key.public_key()}
    )()
    token = jwt.encode(
        {
            "iss": "https://tenant.cloudflareaccess.com",
            "aud": "another-audience",
            "sub": "invitee-a",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(AuthenticationError, match="Invalid"):
        verifier.verify(token)
