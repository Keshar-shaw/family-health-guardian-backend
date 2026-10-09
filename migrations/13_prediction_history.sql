-- Phase 2 Prediction History Schema Migration
-- Family Health Guardian

-- 1. Create prediction_history table
CREATE TABLE IF NOT EXISTS public.prediction_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    family_id UUID REFERENCES public.families(id) ON DELETE CASCADE,
    family_member_id UUID REFERENCES public.family_members(id) ON DELETE SET NULL,
    prediction_type TEXT NOT NULL DEFAULT 'DIABETES',
    model_version TEXT NOT NULL DEFAULT '1.0.0',
    model_name TEXT NOT NULL DEFAULT 'RandomForestClassifier',
    input_measurements JSONB NOT NULL,
    prediction_result INTEGER NOT NULL,
    risk_label TEXT NOT NULL,
    risk_probability NUMERIC(5, 4) NOT NULL,
    risk_percentage NUMERIC(5, 2) NOT NULL,
    confidence_level TEXT NOT NULL,
    recommendations JSONB DEFAULT '[]'::jsonb NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Performance and lookup indexes
CREATE INDEX IF NOT EXISTS idx_prediction_history_user_id ON public.prediction_history(user_id);
CREATE INDEX IF NOT EXISTS idx_prediction_history_family_id ON public.prediction_history(family_id);
CREATE INDEX IF NOT EXISTS idx_prediction_history_family_member_id ON public.prediction_history(family_member_id);
CREATE INDEX IF NOT EXISTS idx_prediction_history_type ON public.prediction_history(prediction_type);
CREATE INDEX IF NOT EXISTS idx_prediction_history_created_at ON public.prediction_history(created_at DESC);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.prediction_history ENABLE ROW LEVEL SECURITY;

-- 3. RLS Policies
-- Users can view their own predictions or authorized family/member predictions
DROP POLICY IF EXISTS "Users can view authorized prediction history" ON public.prediction_history;
CREATE POLICY "Users can view authorized prediction history"
ON public.prediction_history FOR SELECT
USING (
    auth.uid() = user_id
    OR (family_member_id IS NOT NULL AND public.can_read_health_record(family_member_id, auth.uid()))
    OR (family_id IS NOT NULL AND public.is_family_member(family_id, auth.uid()))
);

-- Users can insert predictions for themselves or for authorized family members
DROP POLICY IF EXISTS "Users can insert authorized prediction history" ON public.prediction_history;
CREATE POLICY "Users can insert authorized prediction history"
ON public.prediction_history FOR INSERT
WITH CHECK (
    auth.uid() = user_id
    AND (
        family_id IS NULL
        OR public.is_family_member(family_id, auth.uid())
    )
    AND (
        family_member_id IS NULL
        OR public.can_write_health_record(family_member_id, auth.uid())
    )
);

-- Users can delete their own prediction history records
DROP POLICY IF EXISTS "Users can delete own prediction history" ON public.prediction_history;
CREATE POLICY "Users can delete own prediction history"
ON public.prediction_history FOR DELETE
USING (
    auth.uid() = user_id
);
