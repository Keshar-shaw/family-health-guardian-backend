-- Phase 2 Notification Foundation Schema Migration
-- Family Health Guardian

-- 1. Create Enums for Notification Type and Status
DO $$ BEGIN
    CREATE TYPE notification_type AS ENUM ('MEDICINE_REMINDER', 'EMERGENCY_SOS');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE notification_status AS ENUM ('PENDING', 'SENT', 'FAILED', 'READ');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2. Create notifications table
CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    family_member_id UUID NOT NULL REFERENCES public.family_members(id) ON DELETE CASCADE,
    type notification_type NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    status notification_status NOT NULL DEFAULT 'PENDING',
    scheduled_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON public.notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_family_member_id ON public.notifications(family_member_id);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON public.notifications(status);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON public.notifications(type);
CREATE INDEX IF NOT EXISTS idx_notifications_scheduled_at ON public.notifications(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON public.notifications(created_at);

-- 3. Enable Row Level Security (RLS)
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

-- 4. RLS Policies
-- Users can only view their own notifications
DROP POLICY IF EXISTS "Users can view their own notifications" ON public.notifications;
CREATE POLICY "Users can view their own notifications"
ON public.notifications FOR SELECT
USING (auth.uid() = user_id);

-- Users can update (e.g. mark as READ) their own notifications
DROP POLICY IF EXISTS "Users can update their own notifications" ON public.notifications;
CREATE POLICY "Users can update their own notifications"
ON public.notifications FOR UPDATE
USING (auth.uid() = user_id);

-- System or authorized family members can insert notifications
DROP POLICY IF EXISTS "Authorized members can insert notifications" ON public.notifications;
CREATE POLICY "Authorized members can insert notifications"
ON public.notifications FOR INSERT
WITH CHECK (
    auth.uid() = user_id
    OR public.can_read_health_record(family_member_id, auth.uid())
    OR public.can_access_sos_event(family_member_id, auth.uid())
);

-- Users can delete their own notifications
DROP POLICY IF EXISTS "Users can delete their own notifications" ON public.notifications;
CREATE POLICY "Users can delete their own notifications"
ON public.notifications FOR DELETE
USING (auth.uid() = user_id);
