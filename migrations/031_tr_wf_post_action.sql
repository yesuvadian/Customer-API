-- Migration 031: Add post_action column to tr_wf_stage_transitions
-- Allows admin-configured post-transition actions fired via reflection-based registry.

ALTER TABLE tr_wf_stage_transitions
    ADD COLUMN IF NOT EXISTS post_action VARCHAR(100) NULL;

COMMENT ON COLUMN tr_wf_stage_transitions.post_action
    IS 'Key into BaseWfAction registry (services/tr_wf_post_actions.py). Fired after transition completes.';
