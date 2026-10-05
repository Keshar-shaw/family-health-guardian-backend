-- Phase 2 Health Records Schema Migration
-- Family Health Guardian

-- 1. Create health_records table
CREATE TABLE IF NOT EXISTS public.health_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_member_id UUID NOT NULL REFERENCES public.family_members(id) ON DELETE CASCADE,
    blood_group TEXT,
    allergies TEXT,
    chronic_conditions TEXT,
    medical_history TEXT,
    current_conditions TEXT,
    doctor_name TEXT,
    doctor_contact TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Index for fast lookup by family member
CREATE INDEX IF NOT EXISTS idx_health_records_family_member_id ON public.health_records(family_member_id);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.health_records ENABLE ROW LEVEL SECURITY;

-- 3. Security Definer Helper Functions for Health Record Access
CREATE OR REPLACE FUNCTION public.can_read_health_record(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
DECLARE
    target_user_id UUID;
    target_family_id UUID;
BEGIN
    SELECT user_id, family_id INTO target_user_id, target_family_id
    FROM public.family_members
    WHERE id = _family_member_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Self access is always granted
    IF target_user_id = _user_id THEN
        RETURN TRUE;
    END IF;

    -- Active consent check (either READ_ONLY or FULL_ACCESS) within the same family
    RETURN EXISTS (
        SELECT 1
        FROM public.consents
        WHERE granter_id = target_user_id
          AND grantee_id = _user_id
          AND family_id = target_family_id
          AND status = 'ACTIVE'
          AND permission_level IN ('READ_ONLY', 'FULL_ACCESS')
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.can_write_health_record(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
DECLARE
    target_user_id UUID;
    target_family_id UUID;
BEGIN
    SELECT user_id, family_id INTO target_user_id, target_family_id
    FROM public.family_members
    WHERE id = _family_member_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Self access is always granted
    IF target_user_id = _user_id THEN
        RETURN TRUE;
    END IF;

    -- Active consent check with FULL_ACCESS within the same family
    RETURN EXISTS (
        SELECT 1
        FROM public.consents
        WHERE granter_id = target_user_id
          AND grantee_id = _user_id
          AND family_id = target_family_id
          AND status = 'ACTIVE'
          AND permission_level = 'FULL_ACCESS'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 4. RLS Policies
DROP POLICY IF EXISTS "Users can view health records with self or active consent" ON public.health_records;
CREATE POLICY "Users can view health records with self or active consent"
ON public.health_records FOR SELECT
USING (
    public.can_read_health_record(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can insert health records with self or active full access consent" ON public.health_records;
CREATE POLICY "Users can insert health records with self or active full access consent"
ON public.health_records FOR INSERT
WITH CHECK (
    public.can_write_health_record(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can update health records with self or active full access consent" ON public.health_records;
CREATE POLICY "Users can update health records with self or active full access consent"
ON public.health_records FOR UPDATE
USING (
    public.can_write_health_record(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can delete health records with self or active full access consent" ON public.health_records;
CREATE POLICY "Users can delete health records with self or active full access consent"
ON public.health_records FOR DELETE
USING (
    public.can_write_health_record(family_member_id, auth.uid())
);
