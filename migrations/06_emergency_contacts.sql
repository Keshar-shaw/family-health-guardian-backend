-- Phase 2 Emergency Contacts Schema Migration
-- Family Health Guardian

-- 1. Create emergency_contacts table
CREATE TABLE IF NOT EXISTS public.emergency_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_member_id UUID NOT NULL REFERENCES public.family_members(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    relationship TEXT,
    phone TEXT NOT NULL,
    email TEXT,
    priority INT NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_emergency_contacts_family_member_id ON public.emergency_contacts(family_member_id);
CREATE INDEX IF NOT EXISTS idx_emergency_contacts_priority ON public.emergency_contacts(priority);
CREATE INDEX IF NOT EXISTS idx_emergency_contacts_is_active ON public.emergency_contacts(is_active);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.emergency_contacts ENABLE ROW LEVEL SECURITY;

-- 3. Security Definer Helper Functions for Emergency Contact Access
CREATE OR REPLACE FUNCTION public.can_read_emergency_contact(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
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

CREATE OR REPLACE FUNCTION public.can_write_emergency_contact(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
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

-- 4. RLS Policies for Emergency Contacts
DROP POLICY IF EXISTS "Users can view emergency contacts with self or active consent" ON public.emergency_contacts;
CREATE POLICY "Users can view emergency contacts with self or active consent"
ON public.emergency_contacts FOR SELECT
USING (
    public.can_read_emergency_contact(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can insert emergency contacts with self or active full access consent" ON public.emergency_contacts;
CREATE POLICY "Users can insert emergency contacts with self or active full access consent"
ON public.emergency_contacts FOR INSERT
WITH CHECK (
    public.can_write_emergency_contact(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can update emergency contacts with self or active full access consent" ON public.emergency_contacts;
CREATE POLICY "Users can update emergency contacts with self or active full access consent"
ON public.emergency_contacts FOR UPDATE
USING (
    public.can_write_emergency_contact(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can delete emergency contacts with self or active full access consent" ON public.emergency_contacts;
CREATE POLICY "Users can delete emergency contacts with self or active full access consent"
ON public.emergency_contacts FOR DELETE
USING (
    public.can_write_emergency_contact(family_member_id, auth.uid())
);
