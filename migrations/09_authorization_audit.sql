-- Phase 2 Authorization Hardening & Audit Migration
-- Family Health Guardian

-- 1. Hardened Health Records Access Functions
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

    -- Active consent check: grantee must also currently be a member of the same family
    RETURN EXISTS (
        SELECT 1
        FROM public.consents c
        JOIN public.family_members fm ON fm.family_id = target_family_id AND fm.user_id = _user_id
        WHERE c.granter_id = target_user_id
          AND c.grantee_id = _user_id
          AND c.family_id = target_family_id
          AND c.status = 'ACTIVE'
          AND c.permission_level IN ('READ_ONLY', 'FULL_ACCESS')
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

    -- Active consent check with FULL_ACCESS: grantee must currently be a member of the same family
    RETURN EXISTS (
        SELECT 1
        FROM public.consents c
        JOIN public.family_members fm ON fm.family_id = target_family_id AND fm.user_id = _user_id
        WHERE c.granter_id = target_user_id
          AND c.grantee_id = _user_id
          AND c.family_id = target_family_id
          AND c.status = 'ACTIVE'
          AND c.permission_level = 'FULL_ACCESS'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 2. Hardened Medicine Access Functions
CREATE OR REPLACE FUNCTION public.can_read_medicine(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
BEGIN
    RETURN public.can_read_health_record(_family_member_id, _user_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.can_write_medicine(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
BEGIN
    RETURN public.can_write_health_record(_family_member_id, _user_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3. Hardened Emergency Contact Access Functions
CREATE OR REPLACE FUNCTION public.can_read_emergency_contact(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
BEGIN
    RETURN public.can_read_health_record(_family_member_id, _user_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.can_write_emergency_contact(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
BEGIN
    RETURN public.can_write_health_record(_family_member_id, _user_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 4. Hardened Consents Policies
DROP POLICY IF EXISTS "Users can create consents" ON public.consents;
CREATE POLICY "Users can create consents"
ON public.consents FOR INSERT
WITH CHECK (
    (auth.uid() = granter_id OR auth.uid() = grantee_id)
    AND granter_id <> grantee_id
    AND public.is_family_member(family_id, granter_id)
    AND public.is_family_member(family_id, grantee_id)
);

DROP POLICY IF EXISTS "Granter or grantee can update consents" ON public.consents;
CREATE POLICY "Granter or grantee can update consents"
ON public.consents FOR UPDATE
USING (auth.uid() = granter_id OR auth.uid() = grantee_id)
WITH CHECK (
    -- Only the granter (data owner) can approve (ACTIVE) or modify permission levels
    (
        auth.uid() = granter_id
    ) OR (
        auth.uid() = grantee_id AND status IN ('REVOKED', 'DENIED')
    )
);

-- 5. Complete CRUD Policies for Families
DROP POLICY IF EXISTS "Family admins can delete families" ON public.families;
CREATE POLICY "Family admins can delete families"
ON public.families FOR DELETE
USING (
    public.is_family_admin(id, auth.uid())
);

-- 6. Complete CRUD Policies for Medical Reports
DROP POLICY IF EXISTS "Users can update medical reports with self or active full access consent" ON public.medical_reports;
CREATE POLICY "Users can update medical reports with self or active full access consent"
ON public.medical_reports FOR UPDATE
USING (
    public.can_write_health_record(family_member_id, auth.uid())
);

-- 7. Complete CRUD Policies for SOS Events
DROP POLICY IF EXISTS "Family members or triggerer can delete emergency SOS" ON public.sos_events;
CREATE POLICY "Family members or triggerer can delete emergency SOS"
ON public.sos_events FOR DELETE
USING (
    public.can_access_sos_event(family_member_id, auth.uid()) OR triggered_by = auth.uid()
);
