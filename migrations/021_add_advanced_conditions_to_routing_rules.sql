-- Migration 021: Add advanced_conditions to notification_routing_rules
-- Stores per-rule scope refinements such as specific test type names.
-- {"activity_types": ["Short Circuit Test HV-IV", "Transformer Oil Test"]}

ALTER TABLE public.notification_routing_rules
    ADD COLUMN IF NOT EXISTS advanced_conditions JSONB;
