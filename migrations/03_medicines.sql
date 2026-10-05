-- Phase 2 Medicines Schema Migration
-- Family Health Guardian

-- 1. Create medicines table
CREATE TABLE IF NOT EXISTS public.medicines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_member_id UUID NOT NULL REFERENCES public.family_members(id) ON DELETE CASCADE,
    medicine_name TEXT NOT NULL,
    dosage TEXT,
    dosage_unit TEXT,
    frequency TEXT,
    route TEXT,
    start_date DATE,
    end_date DATE,
    prescribed_by TEXT,
    instructions TEXT,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Index for fast lookup by family member and active status
CREATE INDEX IF NOT EXISTS idx_medicines_family_member_id ON public.medicines(family_member_id);
CREATE INDEX IF NOT EXISTS idx_medicines_is_active ON public.medicines(is_active);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.medicines ENABLE ROW LEVEL SECURITY;

-- 3. Security Definer Helper Functions for Medicine Access
CREATE OR REPLACE FUNCTION public.can_read_medicine(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
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

CREATE OR REPLACE FUNCTION public.can_write_medicine(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
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

-- 4. RLS Policies for Medicines
DROP POLICY IF EXISTS "Users can view medicines with self or active consent" ON public.medicines;
CREATE POLICY "Users can view medicines with self or active consent"
ON public.medicines FOR SELECT
USING (
    public.can_read_medicine(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can insert medicines with self or active full access consent" ON public.medicines;
CREATE POLICY "Users can insert medicines with self or active full access consent"
ON public.medicines FOR INSERT
WITH CHECK (
    public.can_write_medicine(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can update medicines with self or active full access consent" ON public.medicines;
CREATE POLICY "Users can update medicines with self or active full access consent"
ON public.medicines FOR UPDATE
USING (
    public.can_write_medicine(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can delete medicines with self or active full access consent" ON public.medicines;
CREATE POLICY "Users can delete medicines with self or active full access consent"
ON public.medicines FOR DELETE
USING (
    public.can_write_medicine(family_member_id, auth.uid())
);
