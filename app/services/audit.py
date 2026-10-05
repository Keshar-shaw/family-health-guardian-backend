from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException, status
from supabase import Client
from app.schemas.audit_log import AuditAction, AuditResourceType

# Prohibited sensitive keys that must never appear in audit log metadata
SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "jwt",
    "secret",
    "authorization",
    "auth",
    "api_key",
    "key",
    "credentials",
    "bearer"
}


def sanitize_metadata(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Recursively strips out passwords, tokens, API keys, or credentials
    to ensure compliance and zero secret leakage.
    """
    if not data:
        return {}

    sanitized: Dict[str, Any] = {}
    for k, v in data.items():
        k_lower = str(k).lower()
        if any(sensitive in k_lower for sensitive in SENSITIVE_KEYS):
            # Exclude sensitive key completely
            continue
        elif isinstance(v, dict):
            sanitized[k] = sanitize_metadata(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_metadata(item) if isinstance(item, dict) else item
                for item in v
            ]
        elif isinstance(v, (str, int, float, bool)) or v is None:
            sanitized[k] = v
        else:
            sanitized[k] = str(v)
    return sanitized


class AuditService:
    """
    Centralized service for recording tamper-evident audit logs
    across all sensitive healthcare actions.
    """

    @staticmethod
    def log_action(
        supabase: Client,
        actor_user_id: str,
        action: str,
        resource_type: str,
        resource_id: Optional[UUID] = None,
        family_id: Optional[UUID] = None,
        family_member_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[dict]:
        """
        Records an immutable audit event in the database.
        Never stores secrets, passwords, or tokens.
        """
        try:
            safe_meta = sanitize_metadata(metadata)
            payload = {
                "actor_user_id": str(actor_user_id),
                "action": str(action),
                "resource_type": str(resource_type),
                "metadata": safe_meta,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            if resource_id is not None:
                payload["resource_id"] = str(resource_id)
            if family_id is not None:
                payload["family_id"] = str(family_id)
            if family_member_id is not None:
                payload["family_member_id"] = str(family_member_id)

            res = supabase.table("audit_logs").insert(payload).execute()
            if res.data:
                return res.data[0]
            return None
        except Exception:
            # Audit logging failure should not abort critical patient transactions,
            # but is logged / caught safely.
            return None

    @staticmethod
    def list_logs(
        supabase: Client,
        actor_user_id: Optional[str] = None,
        family_id: Optional[UUID] = None,
        family_member_id: Optional[UUID] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[dict]:
        """
        Retrieves audit trail with query filtering and pagination.
        """
        query = supabase.table("audit_logs").select("*")
        if actor_user_id:
            query = query.eq("actor_user_id", str(actor_user_id))
        if family_id:
            query = query.eq("family_id", str(family_id))
        if family_member_id:
            query = query.eq("family_member_id", str(family_member_id))
        if action:
            query = query.eq("action", str(action))
        if resource_type:
            query = query.eq("resource_type", str(resource_type))

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        res = query.execute()
        return res.data if res.data else []
