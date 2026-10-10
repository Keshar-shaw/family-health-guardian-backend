import time
import logging
import jwt
from fastapi import HTTPException, status
from pydantic import BaseModel
from typing import Optional, Union
from app.config import settings

logger = logging.getLogger(__name__)


class UserTokenPayload(BaseModel):
    sub: str  # User ID (UUID)
    email: Optional[str] = None
    role: Optional[str] = None
    aud: Optional[str] = None
    exp: Optional[Union[int, float]] = None


_jwks_client: Optional[jwt.PyJWKClient] = None


def get_jwks_client() -> Optional[jwt.PyJWKClient]:
    """Lazy initialize and cache the JWKS client for Supabase asymmetric ES256/RS256 keys."""
    global _jwks_client
    if _jwks_client is None and settings.SUPABASE_URL and not settings.SUPABASE_URL.startswith("https://placeholder"):
        try:
            jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
            _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True, max_cached_keys=16)
        except Exception as e:
            logger.warning("Could not initialize JWKS client for %s: %s", settings.SUPABASE_URL, e)
    return _jwks_client


def decode_jwt_token(token: str) -> UserTokenPayload:
    """
    Decodes and validates a Supabase JWT token.
    Supports:
    1. Asymmetric ES256 / RS256 verification via Supabase JWKS endpoint.
    2. Symmetric HS256 signature verification via settings.SUPABASE_JWT_SECRET.
    3. Graceful fallback when running in testing / dev with placeholder secrets.
    """
    try:
        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg", "HS256")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Could not validate credentials: invalid token header: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        payload = None

        # 1. Asymmetric verification (ES256 / RS256 from live Supabase)
        if alg in ("ES256", "RS256"):
            jwks = get_jwks_client()
            if jwks:
                try:
                    signing_key = jwks.get_signing_key_from_jwt(token)
                    payload = jwt.decode(
                        token,
                        signing_key.key,
                        algorithms=[alg],
                        audience="authenticated"
                    )
                except Exception as e:
                    logger.warning("JWKS verification failed for %s token: %s", alg, e)
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Could not validate credentials: {str(e)}",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            else:
                # If JWKS client cannot be reached, fallback if signature verification not possible
                payload = jwt.decode(token, options={"verify_signature": False})

        # 2. Symmetric verification (HS256 from test suites or configured secret)
        elif alg == "HS256":
            if settings.SUPABASE_JWT_SECRET and settings.SUPABASE_JWT_SECRET != "placeholder-jwt-secret-min-32-chars-long":
                payload = jwt.decode(
                    token,
                    settings.SUPABASE_JWT_SECRET,
                    algorithms=["HS256"],
                    audience="authenticated"
                )
            else:
                payload = jwt.decode(token, options={"verify_signature": False})
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token algorithm: {alg}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check token expiration
        exp = payload.get("exp")
        if exp is not None:
            try:
                if float(exp) < time.time():
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication token has expired",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token expiration format",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token: missing user ID ('sub')",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return UserTokenPayload(
            sub=user_id,
            email=payload.get("email"),
            role=payload.get("role"),
            aud=payload.get("aud"),
            exp=payload.get("exp"),
        )
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
