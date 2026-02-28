-- ============================================================
-- Solasta Smart Study Scheduler — Supabase Schema
-- Run this in the Supabase SQL Editor
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Users ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE,
    display_name TEXT,
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);

-- ── Goals ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS goals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    raw_input TEXT NOT NULL,
    parsed_objective TEXT DEFAULT '',
    constraints JSONB DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'planning', 'executing', 'paused', 'completed', 'failed')),
    active_plan_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_goals_user_id ON goals(user_id);
CREATE INDEX idx_goals_status ON goals(status);
CREATE INDEX idx_goals_created_at ON goals(created_at DESC);

-- ── Plans (Versioned) ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal_id UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (goal_id, version)
);

CREATE INDEX idx_plans_goal_id ON plans(goal_id);
CREATE INDEX idx_plans_active ON plans(goal_id, is_active) WHERE is_active = TRUE;

-- ── Steps ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    expected_outcome TEXT DEFAULT '',
    thought_process TEXT DEFAULT '',
    priority TEXT DEFAULT 'medium' CHECK (priority IN ('high', 'medium', 'low')),
    dependencies JSONB DEFAULT '[]',
    required_tools JSONB DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'evaluating', 'completed', 'failed', 'skipped', 'replanned')),
    result_payload JSONB,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_steps_plan_id ON steps(plan_id);
CREATE INDEX idx_steps_status ON steps(status);
CREATE INDEX idx_steps_step_id ON steps(step_id);

-- ── Agent Logs (Immutable Audit Trail) ────────────────────

CREATE TABLE IF NOT EXISTS agent_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal_id UUID REFERENCES goals(id) ON DELETE CASCADE,
    plan_id UUID REFERENCES plans(id) ON DELETE SET NULL,
    step_id TEXT,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('planner', 'executor', 'evaluator', 'replanner', 'summariser')),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_summary TEXT,
    response_summary TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    error TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_logs_goal_id ON agent_logs(goal_id);
CREATE INDEX idx_agent_logs_agent_type ON agent_logs(agent_type);
CREATE INDEX idx_agent_logs_timestamp ON agent_logs(timestamp DESC);

-- ── Long-Term Memory ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS long_term_memory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal_id UUID REFERENCES goals(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    outcome JSONB DEFAULT '{}',
    embedding VECTOR(1536),  -- For pgvector similarity search
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_memory_created_at ON long_term_memory(created_at DESC);

-- ── Performance Metrics ──────────────────────────────────

CREATE TABLE IF NOT EXISTS performance_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal_id UUID REFERENCES goals(id) ON DELETE CASCADE,
    total_steps INTEGER DEFAULT 0,
    completed_steps INTEGER DEFAULT 0,
    failed_steps INTEGER DEFAULT 0,
    total_replans INTEGER DEFAULT 0,
    total_tokens_used INTEGER DEFAULT 0,
    total_latency_ms INTEGER DEFAULT 0,
    success_rate FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_metrics_goal_id ON performance_metrics(goal_id);

-- ── RLS Policies (Row Level Security) ─────────────────────

ALTER TABLE goals ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to manage their own data
CREATE POLICY "Users can manage own goals" ON goals
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can view plans for own goals" ON plans
    FOR SELECT USING (goal_id IN (SELECT id FROM goals WHERE user_id = auth.uid()));

CREATE POLICY "Users can view steps for own plans" ON steps
    FOR SELECT USING (plan_id IN (
        SELECT p.id FROM plans p JOIN goals g ON p.goal_id = g.id WHERE g.user_id = auth.uid()
    ));

CREATE POLICY "Users can view own agent logs" ON agent_logs
    FOR SELECT USING (goal_id IN (SELECT id FROM goals WHERE user_id = auth.uid()));
