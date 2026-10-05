from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from typing import List, Optional
from datetime import date
from uuid import UUID
import uuid
import os

from app.auth.dependencies import get_current_user, get_supabase
from app.auth.jwt import UserTokenPayload
from app.api.health_records import verify_member_access
from app.schemas.medical_report import (
    MedicalReportResponse,
)
from supabase import Client

router = APIRouter(prefix="/medical-reports", tags=["Medical Reports"])

STORAGE_BUCKET = "medical-reports"
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
}

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def get_signed_url(supabase: Client, storage_path: str, expires_in: int = 300) -> Optional[str]:
    """Generates a secure, short-lived signed URL for accessing private storage files."""
    try:
        res = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(storage_path, expires_in)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")
        return str(res) if res else None
    except Exception:
        return None


@router.post("", response_model=MedicalReportResponse, status_code=status.HTTP_201_CREATED)
async def upload_medical_report(
    file: UploadFile = File(..., description="PDF, JPG, or PNG report file"),
    family_member_id: UUID = Form(..., description="Target family member"),
    report_type: str = Form("GENERAL", description="Report classification (LAB_REPORT, PRESCRIPTION, etc.)"),
    report_date: Optional[date] = Form(None, description="Date report was issued"),
    description: Optional[str] = Form(None, description="Optional diagnostic notes or summary"),
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Upload a medical report document (PDF, JPG, PNG).
    - File binary is securely stored in private Supabase Storage.
    - Report metadata is stored in PostgreSQL with RLS.
    - Requires self or ACTIVE FULL_ACCESS consent.
    """
    # 1. Authorize user for the family member
    verify_member_access(
        supabase=supabase,
        family_member_id=family_member_id,
        user_id=current_user.sub,
        require_full_access=True
    )

    # 2. Validate MIME type and file extension
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    content_type = file.content_type.lower() if file.content_type else ""

    if file_ext not in ALLOWED_EXTENSIONS or content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Supported formats are PDF, JPG, and PNG. Received: {file.filename}"
        )

    # 3. Read file contents and validate file size
    contents = await file.read()
    file_size = len(contents)
    if file_size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of 15MB (file size: {file_size / (1024 * 1024):.1f}MB)"
        )

    # 4. Generate unique storage path
    sanitized_filename = os.path.basename(file.filename or "report")
    storage_path = f"{family_member_id}/{uuid.uuid4()}_{sanitized_filename}"

    # 5. Upload binary to private Supabase Storage bucket
    try:
        upload_res = supabase.storage.from_(STORAGE_BUCKET).upload(
            storage_path,
            contents,
            file_options={"content-type": content_type}
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file to secure storage: {str(e)}"
        )

    # 6. Save metadata record to PostgreSQL
    report_dict = {
        "family_member_id": str(family_member_id),
        "uploaded_by": current_user.sub,
        "file_name": sanitized_filename,
        "storage_path": storage_path,
        "report_type": report_type.upper(),
        "mime_type": content_type,
        "file_size": file_size,
        "report_date": str(report_date) if report_date else str(date.today()),
        "description": description,
    }

    res = supabase.table("medical_reports").insert(report_dict).execute()
    if not res.data:
        # Cleanup uploaded file if database insert failed
        supabase.storage.from_(STORAGE_BUCKET).remove([storage_path])
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to save report metadata")

    report_record = res.data[0]
    report_record["download_url"] = get_signed_url(supabase, storage_path, expires_in=300)
    return report_record


@router.get("", response_model=List[MedicalReportResponse])
def list_medical_reports(
    family_member_id: Optional[UUID] = None,
    report_type: Optional[str] = None,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    List medical reports.
    If family_member_id is provided, checks access and lists records for that member.
    If omitted, lists all reports the user has authorized access to view.
    """
    if family_member_id is not None:
        verify_member_access(
            supabase=supabase,
            family_member_id=family_member_id,
            user_id=current_user.sub,
            require_full_access=False
        )
        query = supabase.table("medical_reports").select("*").eq("family_member_id", str(family_member_id))
        if report_type:
            query = query.eq("report_type", report_type.upper())
        res = query.execute()
        reports = res.data if res.data else []
        for r in reports:
            r["download_url"] = get_signed_url(supabase, r["storage_path"], expires_in=300)
        return reports

    # Self members
    self_members = supabase.table("family_members").select("id").eq("user_id", current_user.sub).execute()
    authorized_member_ids = [m["id"] for m in (self_members.data or [])]

    # Active consents
    consents_res = supabase.table("consents").select("granter_id, family_id") \
        .eq("grantee_id", current_user.sub) \
        .eq("status", "ACTIVE") \
        .execute()

    if consents_res.data:
        for c in consents_res.data:
            cm_res = supabase.table("family_members").select("id") \
                .eq("family_id", c["family_id"]) \
                .eq("user_id", c["granter_id"]) \
                .execute()
            if cm_res.data:
                authorized_member_ids.extend([m["id"] for m in cm_res.data])

    if not authorized_member_ids:
        return []

    query = supabase.table("medical_reports").select("*").in_("family_member_id", authorized_member_ids)
    if report_type:
        query = query.eq("report_type", report_type.upper())
    res = query.execute()
    reports = res.data if res.data else []
    for r in reports:
        r["download_url"] = get_signed_url(supabase, r["storage_path"], expires_in=300)
    return reports


@router.get("/{id}", response_model=MedicalReportResponse)
def get_medical_report(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Retrieve metadata and secure time-limited download URL for a medical report by ID.
    Caller must have authorized access to view the patient's records.
    """
    res = supabase.table("medical_reports").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medical report not found")
    report = res.data[0]

    verify_member_access(
        supabase=supabase,
        family_member_id=UUID(report["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=False
    )

    report["download_url"] = get_signed_url(supabase, report["storage_path"], expires_in=300)
    return report


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_medical_report(
    id: UUID,
    current_user: UserTokenPayload = Depends(get_current_user),
    supabase: Client = Depends(get_supabase)
):
    """
    Delete a medical report from PostgreSQL and remove its file binary from Supabase Storage.
    Caller must have ACTIVE FULL_ACCESS consent for the patient.
    """
    res = supabase.table("medical_reports").select("*").eq("id", str(id)).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medical report not found")
    report = res.data[0]

    verify_member_access(
        supabase=supabase,
        family_member_id=UUID(report["family_member_id"]),
        user_id=current_user.sub,
        require_full_access=True
    )

    # 1. Remove file binary from Supabase Storage
    try:
        supabase.storage.from_(STORAGE_BUCKET).remove([report["storage_path"]])
    except Exception:
        pass

    # 2. Delete metadata row
    supabase.table("medical_reports").delete().eq("id", str(id)).execute()
    return None
