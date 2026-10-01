import logging
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)
User = get_user_model()


@database_sync_to_async
def get_user_from_token(token_string: str):
    """
    Decodes the JWT access token and retrieves the active user record.
    Returns AnonymousUser on any validation or lookup failure.
    """
    if not token_string:
        return AnonymousUser()

    try:
        # Validate JWT token signature and expiration
        token = AccessToken(token_string)
        user_id = token.get("user_id")
        if not user_id:
            return AnonymousUser()

        user = User.objects.get(id=user_id, is_active=True, is_deleted=False)
        return user
    except (InvalidToken, TokenError) as e:
        logger.debug(f"Invalid WebSocket JWT token: {e}")
        return AnonymousUser()
    except User.DoesNotExist:
        logger.debug(f"User not found for WebSocket token.")
        return AnonymousUser()
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket token auth: {e}")
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom Channels middleware to authenticate WebSocket connections using JWT tokens.
    Extracts token from query string (e.g. ?token=<JWT>) or Authorization headers.
    """

    async def __call__(self, scope, receive, send):
        # Default to AnonymousUser
        scope["user"] = AnonymousUser()

        token = None

        # 1. Look for token in query string: ?token=...
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        if "token" in query_params and query_params["token"]:
            token = query_params["token"][0]

        # 2. Fallback: Look for Bearer token in headers
        if not token and "headers" in scope:
            headers = dict(scope["headers"])
            auth_header = headers.get(b"authorization", b"").decode("utf-8")
            if auth_header.startswith("Bearer "):
                token = auth_header.split("Bearer ")[1].strip()

        # 3. Authenticate user asynchronously
        if token:
            scope["user"] = await get_user_from_token(token)

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """Convenience helper wrapping inner ASGI app with JWT authentication."""
    return JWTAuthMiddleware(inner)
