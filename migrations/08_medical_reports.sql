-- Phase 2 Medical Reports Schema Migration
-- Family Health Guardian

-- 1. Create medical_reports metadata table
CREATE TABLE IF NOT EXISTS public.medical_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_member_id UUID NOT NULL REFERENCES public.family_members(id) ON DELETE CASCADE,
    uploaded_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'GENERAL',
    mime_type TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    report_date DATE NOT NULL DEFAULT CURRENT_DATE,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_medical_reports_family_member_id ON public.medical_reports(family_member_id);
CREATE INDEX IF NOT EXISTS idx_medical_reports_uploaded_by ON public.medical_reports(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_medical_reports_report_type ON public.medical_reports(report_type);
CREATE INDEX IF NOT EXISTS idx_medical_reports_report_date ON public.medical_reports(report_date);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.medical_reports ENABLE ROW LEVEL SECURITY;

-- 3. RLS Policies for Medical Reports Metadata
DROP POLICY IF EXISTS "Users can view medical reports with self or active consent" ON public.medical_reports;
CREATE POLICY "Users can view medical reports with self or active consent"
ON public.medical_reports FOR SELECT
USING (
    public.can_read_health_record(family_member_id, auth.uid())
);

DROP POLICY IF EXISTS "Users can insert medical reports with self or active full access consent" ON public.medical_reports;
CREATE POLICY "Users can insert medical reports with self or active full access consent"
ON public.medical_reports FOR INSERT
WITH CHECK (
    public.can_write_health_record(family_member_id, auth.uid()) AND uploaded_by = auth.uid()
);

DROP POLICY IF EXISTS "Users can delete medical reports with self or active full access consent" ON public.medical_reports;
CREATE POLICY "Users can delete medical reports with self or active full access consent"
ON public.medical_reports FOR DELETE
USING (
    public.can_write_health_record(family_member_id, auth.uid())
);

-- 4. Supabase Storage Bucket Initialization (Private bucket: medical-reports)
INSERT INTO storage.buckets (id, name, public)
VALUES ('medical-reports', 'medical-reports', false)
ON CONFLICT (id) DO NOTHING;

-- Storage RLS Policies
DROP POLICY IF EXISTS "Authorized users can read medical report files" ON storage.objects;
CREATE POLICY "Authorized users can read medical report files"
ON storage.objects FOR SELECT
USING (
    bucket_id = 'medical-reports'
    AND auth.role() = 'authenticated'
);

DROP POLICY IF EXISTS "Authorized users can upload medical report files" ON storage.objects;
CREATE POLICY "Authorized users can upload medical report files"
ON storage.objects FOR INSERT
WITH CHECK (
    bucket_id = 'medical-reports'
    AND auth.role() = 'authenticated'
);

DROP POLICY IF EXISTS "Authorized users can delete medical report files" ON storage.objects;
CREATE POLICY "Authorized users can delete medical report files"
ON storage.objects FOR DELETE
USING (
    bucket_id = 'medical-reports'
    AND auth.role() = 'authenticated'
);
