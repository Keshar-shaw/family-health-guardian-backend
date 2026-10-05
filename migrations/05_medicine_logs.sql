-- Phase 2 Medicine Logs Schema Migration
-- Family Health Guardian

-- 1. Create Enum for Log Status
DO $$ BEGIN
    CREATE TYPE medicine_log_status AS ENUM ('TAKEN', 'MISSED', 'SKIPPED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2. Create medicine_logs table
CREATE TABLE IF NOT EXISTS public.medicine_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    medicine_id UUID NOT NULL REFERENCES public.medicines(id) ON DELETE CASCADE,
    schedule_id UUID REFERENCES public.medicine_schedules(id) ON DELETE SET NULL,
    family_member_id UUID NOT NULL REFERENCES public.family_members(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMPTZ,
    taken_at TIMESTAMPTZ,
    status medicine_log_status NOT NULL DEFAULT 'TAKEN',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_medicine_logs_family_member_id ON public.medicine_logs(family_member_id);
CREATE INDEX IF NOT EXISTS idx_medicine_logs_medicine_id ON public.medicine_logs(medicine_id);
CREATE INDEX IF NOT EXISTS idx_medicine_logs_schedule_id ON public.medicine_logs(schedule_id);
CREATE INDEX IF NOT EXISTS idx_medicine_logs_status ON public.medicine_logs(status);

-- 3. Enable Row Level Security (RLS)
ALTER TABLE public.medicine_logs ENABLE ROW LEVEL SECURITY;

-- 4. RLS Policies for Medicine Logs
DROP POLICY IF EXISTS "Users can view medicine logs with self or active consent" ON public.medicine_logs;
CREATE POLICY "Users can view medicine logs with self or active consent"
ON public.medicine_logs FOR SELECT
USING (
    public.can_read_medicine(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can insert medicine logs with self or active full access consent" ON public.medicine_logs;
CREATE POLICY "Users can insert medicine logs with self or active full access consent"
ON public.medicine_logs FOR INSERT
WITH CHECK (
    public.can_write_medicine(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can update medicine logs with self or active full access consent" ON public.medicine_logs;
CREATE POLICY "Users can update medicine logs with self or active full access consent"
ON public.medicine_logs FOR UPDATE
USING (
    public.can_write_medicine(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can delete medicine logs with self or active full access consent" ON public.medicine_logs;
CREATE POLICY "Users can delete medicine logs with self or active full access consent"
ON public.medicine_logs FOR DELETE
USING (
    public.can_write_medicine(family_member_id, auth.uid())
);
