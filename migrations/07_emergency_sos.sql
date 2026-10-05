-- Phase 2 Emergency SOS Schema Migration
-- Family Health Guardian

-- 1. Create Enum for SOS Event Status
DO $$ BEGIN
    CREATE TYPE sos_event_status AS ENUM ('TRIGGERED', 'ACKNOWLEDGED', 'RESOLVED', 'CANCELLED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2. Create sos_events table
CREATE TABLE IF NOT EXISTS public.sos_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_member_id UUID NOT NULL REFERENCES public.family_members(id) ON DELETE CASCADE,
    triggered_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    status sos_event_status NOT NULL DEFAULT 'TRIGGERED',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    location_accuracy DOUBLE PRECISION,
    triggered_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    resolved_at TIMESTAMPTZ,
    notes TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_sos_events_family_member_id ON public.sos_events(family_member_id);
CREATE INDEX IF NOT EXISTS idx_sos_events_status ON public.sos_events(status);
CREATE INDEX IF NOT EXISTS idx_sos_events_triggered_by ON public.sos_events(triggered_by);
CREATE INDEX IF NOT EXISTS idx_sos_events_triggered_at ON public.sos_events(triggered_at);

-- 3. Enable Row Level Security (RLS)
ALTER TABLE public.sos_events ENABLE ROW LEVEL SECURITY;

-- 4. Security Definer Helper Functions for Emergency SOS Access
CREATE OR REPLACE FUNCTION public.can_access_sos_event(_family_member_id UUID, _user_id UUID DEFAULT auth.uid())
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

    -- Any member in the same family can view / respond to emergency SOS
    RETURN public.is_family_member(target_family_id, _user_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 5. RLS Policies for SOS Events
DROP POLICY IF EXISTS "Family members can view emergency SOS events" ON public.sos_events;
CREATE POLICY "Family members can view emergency SOS events"
ON public.sos_events FOR SELECT
USING (
    public.can_access_sos_event(family_member_id, auth.uid()) OR triggered_by = auth.uid()
);

DROP POLICY IF EXISTS "Family members can trigger emergency SOS" ON public.sos_events;
CREATE POLICY "Family members can trigger emergency SOS"
ON public.sos_events FOR INSERT
WITH CHECK (
    public.can_access_sos_event(family_member_id, auth.uid()) AND triggered_by = auth.uid()
);

DROP POLICY IF EXISTS "Family members can update emergency SOS status" ON public.sos_events;
CREATE POLICY "Family members can update emergency SOS status"
ON public.sos_events FOR UPDATE
USING (
    public.can_access_sos_event(family_member_id, auth.uid())
);
