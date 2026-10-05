-- Phase 2 Audit Logs Schema Migration
-- Family Health Guardian

-- 1. Create audit_logs table
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    family_id UUID REFERENCES public.families(id) ON DELETE SET NULL,
    family_member_id UUID REFERENCES public.family_members(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID,
    metadata JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for audit query performance and compliance
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_user_id ON public.audit_logs(actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_family_id ON public.audit_logs(family_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_family_member_id ON public.audit_logs(family_member_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON public.audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_type ON public.audit_logs(resource_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON public.audit_logs(created_at DESC);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

-- 3. RLS Policies
-- Users can view audit logs for actions they took, or for members in their families
DROP POLICY IF EXISTS "Users can view audit logs for their families" ON public.audit_logs;
CREATE POLICY "Users can view audit logs for their families"
ON public.audit_logs FOR SELECT
USING (
    auth.uid() = actor_user_id
    OR (family_id IS NOT NULL AND public.is_family_member(family_id, auth.uid()))
    OR (family_member_id IS NOT NULL AND public.can_read_health_record(family_member_id, auth.uid()))
);

-- Authenticated users can insert audit logs for their own actions
DROP POLICY IF EXISTS "Authenticated users can insert audit logs" ON public.audit_logs;
CREATE POLICY "Authenticated users can insert audit logs"
ON public.audit_logs FOR INSERT
WITH CHECK (
    auth.uid() = actor_user_id
);

-- NOTE: NO UPDATE or DELETE policies are granted to anyone.
-- Audit logs are strictly immutable and append-only.

-- 4. Database Trigger to Guarantee Immutability
CREATE OR REPLACE FUNCTION public.prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are immutable: update and delete operations are prohibited.';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS trg_prevent_audit_log_modification ON public.audit_logs;
CREATE TRIGGER trg_prevent_audit_log_modification
    BEFORE UPDATE OR DELETE ON public.audit_logs
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_log_modification();
