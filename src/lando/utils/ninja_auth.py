import hashlib
import hmac
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from ninja import NinjaAPI
from ninja.errors import HttpError
from ninja.security import APIKeyHeader, HttpBearer
from typing_extensions import override

from lando.main.auth import AccessTokenLandoOIDCAuthenticationBackend
from lando.main.models.configuration import ConfigurationKey, ConfigurationVariable
from lando.utils.phabricator import PHABRICATOR_API_KEY_HEADER

logger = logging.getLogger(__name__)

PHABRICATOR_WEBHOOK_SIGNATURE_HEADER = "X-Phabricator-Webhook-Signature"


class AccessTokenAuth(HttpBearer):
    """Ninja bearer token-based authenticator delegating verification to the OIDC backend."""

    @override
    def authenticate(self, request: WSGIRequest, token: str) -> User | None:
        """Forward the authenticate request to the LandoOIDCAuthenticationBackend."""
        # The token is extracted in the LandoOIDCAuthenticationBackend, so we don't need
        # to pass it. But we need to inherit from HttpBearer for auth to work with Ninja.
        oidc_auth = AccessTokenLandoOIDCAuthenticationBackend()

        # Django-Ninja sets `request.auth` to the verified token, since
        # some APIs may have authentication without user management. Our
        # access tokens always correspond to a specific user, so set that on
        # the request here. Only overwrite `request.user` on success; on failure
        # leave the `AnonymousUser` set by `AuthenticationMiddleware` in place so
        # downstream code never sees `request.user` as `None`.
        user = oidc_auth.authenticate(request)
        if user:
            request.user = user

        return user


#
# Simple API exposing an authenticated endpoint providing OAuth info.
#

api = NinjaAPI(urls_namespace="auth", auth=AccessTokenAuth())


class PhabricatorTokenAuth(APIKeyHeader):
    """Verify that the Phabricator middleware authenticated the request.

    The `PhabricatorTokenAuthenticationMiddleware` reads the
    `X-Phabricator-API-Key` header and authenticates the user via the
    `PhabricatorTokenAuthenticationBackend`, setting `request.user`.
    This auth class simply verifies that the user was authenticated.
    """

    param_name = PHABRICATOR_API_KEY_HEADER

    def authenticate(self, request: WSGIRequest, key: str | None) -> str | None:
        """Return the API key if the middleware authenticated the user, `None` otherwise.

        Note: `key` is the variable name Django-Ninja expects.
        """
        if not key or not request.user.is_authenticated:
            return None

        return key


class HarbormasterWebhookAuth(APIKeyHeader):
    """Authenticate Phabricator webhook callers by verifying the HMAC signature.

    Phabricator signs each webhook with the webhook's HMAC key and sends the
    hex-encoded HMAC-SHA256 digest of the raw request body in the
    `X-Phabricator-Webhook-Signature` header. We recompute that digest using the
    key stored in the `PHABRICATOR_WEBHOOK_HMAC_KEY` configuration variable (set
    at runtime, no deployment secret needed) and compare. An empty configured
    key rejects all callers so misconfigured environments do not silently accept
    arbitrary webhook payloads.
    """

    param_name = PHABRICATOR_WEBHOOK_SIGNATURE_HEADER

    def authenticate(self, request: WSGIRequest, key: str | None) -> str | None:
        configured_key = ConfigurationVariable.get(
            ConfigurationKey.PHABRICATOR_WEBHOOK_HMAC_KEY, ""
        )

        if not configured_key or not key:
            return None

        expected_signature = hmac.new(
            configured_key.encode("utf-8"),
            request.body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(key, expected_signature):
            return None

        return key


@api.get("/__userinfo__")
def userinfo(request: WSGIRequest) -> JsonResponse:
    """Test endpoint to check token verification.

    Only available in non-prod environments."""
    if not settings.ENVIRONMENT.is_lower:
        raise HttpError(404, "Not Found")
    return JsonResponse({"user_id": str(request.auth)})
