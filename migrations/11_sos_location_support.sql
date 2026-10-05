-- Phase 2 SOS Location Support Migration
-- Family Health Guardian

-- 1. Add accuracy and location_timestamp columns to sos_events
ALTER TABLE public.sos_events
ADD COLUMN IF NOT EXISTS accuracy DOUBLE PRECISION,
ADD COLUMN IF NOT EXISTS location_timestamp TIMESTAMPTZ;

-- Backfill accuracy from location_accuracy if present
UPDATE public.sos_events
SET accuracy = location_accuracy
WHERE accuracy IS NULL AND location_accuracy IS NOT NULL;

-- 2. Add validation constraints on coordinate ranges and accuracy
DO $$ BEGIN
    ALTER TABLE public.sos_events
    ADD CONSTRAINT check_sos_latitude CHECK (latitude IS NULL OR (latitude >= -90.0 AND latitude <= 90.0));
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    ALTER TABLE public.sos_events
    ADD CONSTRAINT check_sos_longitude CHECK (longitude IS NULL OR (longitude >= -180.0 AND longitude <= 180.0));
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    ALTER TABLE public.sos_events
    ADD CONSTRAINT check_sos_accuracy CHECK (accuracy IS NULL OR accuracy >= 0.0);
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 3. Indexes for optional location-based queries
CREATE INDEX IF NOT EXISTS idx_sos_events_location ON public.sos_events(latitude, longitude) WHERE latitude IS NOT NULL;
