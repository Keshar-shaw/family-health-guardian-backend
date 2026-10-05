from supabase import create_client, Client
from app.config import settings


def get_supabase_client() -> Client:
    """Initialize base Supabase client."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


def get_authenticated_supabase_client(access_token: str) -> Client:
    """Initialize Supabase client scoped with user JWT token for RLS."""
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    client.postgrest.auth(access_token)
    return client
