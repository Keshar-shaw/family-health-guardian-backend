-- Phase 1 Schema Migration for Supabase PostgreSQL
-- Family Health Guardian

-- Role Enums
DO $$ BEGIN
    CREATE TYPE family_role AS ENUM ('ADMIN', 'GUARDIAN', 'MEMBER');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE consent_status AS ENUM ('PENDING', 'ACTIVE', 'REVOKED', 'DENIED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE consent_permission AS ENUM ('READ_ONLY', 'FULL_ACCESS');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 1. Profiles Table (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    date_of_birth DATE,
    gender TEXT,
    phone_number TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Trigger to create profile when auth user is created
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, full_name, avatar_url)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email, 'User'),
        NEW.raw_user_meta_data->>'avatar_url'
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 2. Families Table
CREATE TABLE IF NOT EXISTS public.families (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    created_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- 3. Family Members Table (RBAC)
CREATE TABLE IF NOT EXISTS public.family_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES public.families(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    role family_role NOT NULL DEFAULT 'MEMBER',
    joined_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(family_id, user_id)
);

-- 4. Consents Table (Consent-Based Access Control)
CREATE TABLE IF NOT EXISTS public.consents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    granter_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    grantee_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    family_id UUID NOT NULL REFERENCES public.families(id) ON DELETE CASCADE,
    permission_level consent_permission NOT NULL DEFAULT 'READ_ONLY',
    status consent_status NOT NULL DEFAULT 'PENDING',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(granter_id, grantee_id, family_id)
);

-- Enable RLS on all tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.families ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.family_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.consents ENABLE ROW LEVEL SECURITY;

-- RLS POLICIES FOR PROFILES
DROP POLICY IF EXISTS "Users can view self or family member profiles" ON public.profiles;
CREATE POLICY "Users can view self or family member profiles"
ON public.profiles FOR SELECT
USING (
    auth.uid() = id OR
    EXISTS (
        SELECT 1 FROM public.family_members fm1
        JOIN public.family_members fm2 ON fm1.family_id = fm2.family_id
        WHERE fm1.user_id = auth.uid() AND fm2.user_id = profiles.id
    )
);

DROP POLICY IF EXISTS "Users can update their own profile" ON public.profiles;
CREATE POLICY "Users can update their own profile"
ON public.profiles FOR UPDATE
USING (auth.uid() = id);

-- RLS POLICIES FOR FAMILIES
DROP POLICY IF EXISTS "Users can view families they belong to" ON public.families;
CREATE POLICY "Users can view families they belong to"
ON public.families FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM public.family_members
        WHERE family_members.family_id = families.id AND family_members.user_id = auth.uid()
    )
);

DROP POLICY IF EXISTS "Users can create families" ON public.families;
CREATE POLICY "Users can create families"
ON public.families FOR INSERT
WITH CHECK (auth.uid() = created_by);

DROP POLICY IF EXISTS "Family admins can update family info" ON public.families;
CREATE POLICY "Family admins can update family info"
ON public.families FOR UPDATE
USING (
    EXISTS (
        SELECT 1 FROM public.family_members
        WHERE family_members.family_id = families.id 
          AND family_members.user_id = auth.uid() 
          AND family_members.role = 'ADMIN'
    )
);

-- RLS POLICIES FOR FAMILY MEMBERS
DROP POLICY IF EXISTS "Members can view members in their family" ON public.family_members;
CREATE POLICY "Members can view members in their family"
ON public.family_members FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM public.family_members self_fm
        WHERE self_fm.family_id = family_members.family_id AND self_fm.user_id = auth.uid()
    )
);

DROP POLICY IF EXISTS "Admins can insert family members" ON public.family_members;
CREATE POLICY "Admins can insert family members"
ON public.family_members FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.family_members self_fm
        WHERE self_fm.family_id = family_members.family_id 
          AND self_fm.user_id = auth.uid() 
          AND self_fm.role = 'ADMIN'
    ) OR auth.uid() = user_id
);

DROP POLICY IF EXISTS "Admins can delete family members" ON public.family_members;
CREATE POLICY "Admins can delete family members"
ON public.family_members FOR DELETE
USING (
    EXISTS (
        SELECT 1 FROM public.family_members self_fm
        WHERE self_fm.family_id = family_members.family_id 
          AND self_fm.user_id = auth.uid() 
          AND self_fm.role = 'ADMIN'
    ) OR auth.uid() = user_id
);

-- RLS POLICIES FOR CONSENTS
DROP POLICY IF EXISTS "Users can view relevant consents" ON public.consents;
CREATE POLICY "Users can view relevant consents"
ON public.consents FOR SELECT
USING (auth.uid() = granter_id OR auth.uid() = grantee_id);

DROP POLICY IF EXISTS "Users can create consents" ON public.consents;
CREATE POLICY "Users can create consents"
ON public.consents FOR INSERT
WITH CHECK (auth.uid() = granter_id OR auth.uid() = grantee_id);

DROP POLICY IF EXISTS "Granter or grantee can update consents" ON public.consents;
CREATE POLICY "Granter or grantee can update consents"
ON public.consents FOR UPDATE
USING (auth.uid() = granter_id OR auth.uid() = grantee_id);
