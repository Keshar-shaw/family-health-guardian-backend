from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth.jwt import decode_jwt_token, UserTokenPayload
from app.db.supabase import get_authenticated_supabase_client
from supabase import Client

security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserTokenPayload:
    """Dependency to extract and validate current authenticated user from Bearer token."""
    token = credentials.credentials
    return decode_jwt_token(token)


def get_supabase(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Client:
    """Dependency to get Supabase client pre-authenticated with user's JWT token for RLS."""
    token = credentials.credentials
    return get_authenticated_supabase_client(token)
