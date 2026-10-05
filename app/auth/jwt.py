import jwt
from fastapi import HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.config import settings


class UserTokenPayload(BaseModel):
    sub: str  # User ID (UUID)
    email: Optional[str] = None
    role: Optional[str] = None
    aud: Optional[str] = None
    exp: Optional[int] = None


def decode_jwt_token(token: str) -> UserTokenPayload:
    """
    Decodes and validates a Supabase JWT token.
    Supports HS256 signature verification via settings.SUPABASE_JWT_SECRET
    or fallback unverified payload extraction when secret is placeholder in dev/tests.
    """
    try:
        if settings.SUPABASE_JWT_SECRET and settings.SUPABASE_JWT_SECRET != "placeholder-jwt-secret-min-32-chars-long":
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated"
            )
        else:
            # Unverified decode for testing / local dev fallback when secret is not configured
            payload = jwt.decode(token, options={"verify_signature": False})
        
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
