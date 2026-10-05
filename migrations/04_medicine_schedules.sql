-- Phase 2 Medicine Schedules Schema Migration
-- Family Health Guardian

-- 1. Create medicine_schedules table
CREATE TABLE IF NOT EXISTS public.medicine_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    medicine_id UUID NOT NULL REFERENCES public.medicines(id) ON DELETE CASCADE,
    scheduled_time TEXT NOT NULL,
    frequency_type TEXT NOT NULL DEFAULT 'DAILY',
    days_of_week TEXT[],
    start_date DATE,
    end_date DATE,
    reminder_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Index for fast lookup by medicine
CREATE INDEX IF NOT EXISTS idx_medicine_schedules_medicine_id ON public.medicine_schedules(medicine_id);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.medicine_schedules ENABLE ROW LEVEL SECURITY;

-- 3. Security Definer Helper Functions for Medicine Schedule Access
CREATE OR REPLACE FUNCTION public.can_read_medicine_schedule(_medicine_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
DECLARE
    target_family_member_id UUID;
BEGIN
    SELECT family_member_id INTO target_family_member_id
    FROM public.medicines
    WHERE id = _medicine_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    RETURN public.can_read_medicine(target_family_member_id, _user_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.can_write_medicine_schedule(_medicine_id UUID, _user_id UUID DEFAULT auth.uid())
RETURNS BOOLEAN AS $$
DECLARE
    target_family_member_id UUID;
BEGIN
    SELECT family_member_id INTO target_family_member_id
    FROM public.medicines
    WHERE id = _medicine_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    RETURN public.can_write_medicine(target_family_member_id, _user_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 4. RLS Policies for Medicine Schedules
DROP POLICY IF EXISTS "Users can view medicine schedules with self or active consent" ON public.medicine_schedules;
CREATE POLICY "Users can view medicine schedules with self or active consent"
ON public.medicine_schedules FOR SELECT
USING (
    public.can_read_medicine_schedule(medicine_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can insert medicine schedules with self or active full access consent" ON public.medicine_schedules;
CREATE POLICY "Users can insert medicine schedules with self or active full access consent"
ON public.medicine_schedules FOR INSERT
WITH CHECK (
    public.can_write_medicine_schedule(medicine_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can update medicine schedules with self or active full access consent" ON public.medicine_schedules;
CREATE POLICY "Users can update medicine schedules with self or active full access consent"
ON public.medicine_schedules FOR UPDATE
USING (
    public.can_write_medicine_schedule(medicine_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can delete medicine schedules with self or active full access consent" ON public.medicine_schedules;
CREATE POLICY "Users can delete medicine schedules with self or active full access consent"
ON public.medicine_schedules FOR DELETE
USING (
    public.can_write_medicine_schedule(medicine_id, auth.uid())
);
