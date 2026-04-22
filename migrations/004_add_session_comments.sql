-- ============================================================
-- Migration: Add Session Comments Table
-- Description: Adds support for approvers to comment on individual test sessions
-- Date: 2026-04-08
-- ============================================================

BEGIN;

-- ────────────────────────────────────────────────────────────
-- 1. Create session_comments table
-- ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.session_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.test_sessions(id) ON DELETE CASCADE,

    comment TEXT NOT NULL,
    author_id UUID NOT NULL REFERENCES public.users(id),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    modified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────
-- 2. Create indexes
-- ────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_session_comments_session_id ON public.session_comments(session_id);
CREATE INDEX IF NOT EXISTS idx_session_comments_author_id ON public.session_comments(author_id);
CREATE INDEX IF NOT EXISTS idx_session_comments_created_at ON public.session_comments(created_at);

-- ────────────────────────────────────────────────────────────
-- 3. Create trigger to update modified_at
-- ────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.update_session_comment_mts()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modified_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_session_comment_mts
    BEFORE UPDATE ON public.session_comments
    FOR EACH ROW
    EXECUTE FUNCTION public.update_session_comment_mts();

-- ────────────────────────────────────────────────────────────
-- 4. Add comments
-- ────────────────────────────────────────────────────────────

COMMENT ON TABLE public.session_comments IS 'Comments on test sessions (typically by approvers for feedback)';
COMMENT ON COLUMN public.session_comments.session_id IS 'Reference to test_sessions table';
COMMENT ON COLUMN public.session_comments.comment IS 'Comment text/feedback';
COMMENT ON COLUMN public.session_comments.author_id IS 'User who wrote the comment';
COMMENT ON COLUMN public.session_comments.created_at IS 'When comment was created';
COMMENT ON COLUMN public.session_comments.modified_at IS 'When comment was last modified (edited)';

COMMIT;

-- ============================================================
-- Rollback instructions (if needed):
-- ============================================================
-- BEGIN;
-- DROP TRIGGER IF EXISTS trigger_update_session_comment_mts ON public.session_comments;
-- DROP FUNCTION IF EXISTS public.update_session_comment_mts();
-- DROP TABLE IF EXISTS public.session_comments CASCADE;
-- COMMIT;
