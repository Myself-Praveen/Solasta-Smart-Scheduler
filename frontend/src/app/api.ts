/**
 * Solasta — API Client
 *
 * Typed client for communicating with the FastAPI backend.
 * Handles goal creation, plan fetching, SSE streaming, and logs.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Types ────────────────────────────────────────────────────

export interface GoalCreateRequest {
    user_input: string;
    user_id?: string;
}

export interface GoalResponse {
    goal_id: string;
    status: string;
    message: string;
    plan?: Plan | null;
}

export interface Step {
    step_id: string;
    title: string;
    description: string;
    expected_outcome: string;
    thought_process: string;
    priority: string;
    depends_on: string[];
    required_tools: string[];
    status: string;
    result_payload: Record<string, unknown> | null;
    error_message: string | null;
    retry_count: number;
    max_retries: number;
    started_at: string | null;
    completed_at: string | null;
}

export interface Plan {
    id: string;
    goal_id: string;
    version: number;
    is_active: boolean;
    steps: Step[];
    created_at: string;
}

export interface AgentLog {
    id: string;
    goal_id: string;
    plan_id: string | null;
    step_id: string | null;
    agent_type: string;
    provider: string;
    model: string;
    prompt_summary: string;
    response_summary: string;
    tokens_in: number;
    tokens_out: number;
    latency_ms: number;
    error: string | null;
    timestamp: string;
}

export interface StreamEventData {
    status?: string;
    message?: string;
    step_id?: string;
    title?: string;
    plan_id?: string;
    version?: number;
    steps?: Step[];
    result_summary?: string;
    error?: string;
    retry_count?: number;
    timestamp?: string;
}

export interface StreamConnectionOptions {
    reconnectDelayMs?: number;
    maxReconnectDelayMs?: number;
    shouldReconnect?: () => boolean;
    onReconnectAttempt?: (attempt: number) => void;
    onOpen?: () => void;
}

export interface StreamConnection {
    close: () => void;
}

// ── API Functions ────────────────────────────────────────────

export async function createGoal(input: GoalCreateRequest): Promise<GoalResponse> {
    const res = await fetch(`${API_BASE}/api/goals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
    });
    if (!res.ok) throw new Error(`Failed to create goal: ${res.statusText}`);
    return res.json();
}

export async function getGoal(goalId: string) {
    const res = await fetch(`${API_BASE}/api/goals/${goalId}`);
    if (!res.ok) throw new Error(`Failed to fetch goal: ${res.statusText}`);
    return res.json();
}

export async function getPlan(goalId: string): Promise<Plan> {
    const res = await fetch(`${API_BASE}/api/goals/${goalId}/plan`);
    if (!res.ok) throw new Error(`Failed to fetch plan: ${res.statusText}`);
    return res.json();
}

export async function getPlanHistory(goalId: string): Promise<Plan[]> {
    const res = await fetch(`${API_BASE}/api/goals/${goalId}/plan/history`);
    if (!res.ok) throw new Error(`Failed to fetch plan history: ${res.statusText}`);
    return res.json();
}

export async function getGoalLogs(goalId: string): Promise<AgentLog[]> {
    const res = await fetch(`${API_BASE}/api/goals/${goalId}/logs`);
    if (!res.ok) throw new Error(`Failed to fetch logs: ${res.statusText}`);
    return res.json();
}

export function streamGoalEvents(
    goalId: string,
    onEvent: (eventType: string, data: StreamEventData) => void,
    onError?: (error: Event) => void,
): EventSource {
    const source = new EventSource(`${API_BASE}/api/goals/${goalId}/stream`);

    const eventTypes = [
        "goal_status",
        "plan_created",
        "step_update",
        "replanning",
        "goal_completed",
        "goal_failed",
        "error",
        "heartbeat",
    ];

    eventTypes.forEach((type) => {
        source.addEventListener(type, (event: MessageEvent) => {
            try {
                const data = JSON.parse(event.data);
                onEvent(type, data);
            } catch {
                onEvent(type, { message: event.data });
            }
        });
    });

    if (onError) {
        source.onerror = onError;
    }

    return source;
}

export function streamGoalEventsWithReconnect(
    goalId: string,
    onEvent: (eventType: string, data: StreamEventData) => void,
    onError?: (error: Event) => void,
    options?: StreamConnectionOptions,
): StreamConnection {
    const reconnectDelayMs = options?.reconnectDelayMs ?? 1500;
    const maxReconnectDelayMs = options?.maxReconnectDelayMs ?? 15000;
    const shouldReconnect = options?.shouldReconnect ?? (() => true);

    const eventTypes = [
        "goal_status",
        "plan_created",
        "step_update",
        "replanning",
        "goal_completed",
        "goal_failed",
        "error",
        "heartbeat",
    ];

    let source: EventSource | null = null;
    let closed = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | null = null;

    const attachListeners = (es: EventSource) => {
        eventTypes.forEach((type) => {
            es.addEventListener(type, (event: MessageEvent) => {
                try {
                    const data = JSON.parse(event.data);
                    onEvent(type, data);
                } catch {
                    onEvent(type, { message: event.data });
                }
            });
        });

        es.onopen = () => {
            reconnectAttempt = 0;
            options?.onOpen?.();
        };

        es.onerror = (error: Event) => {
            onError?.(error);
            es.close();

            if (closed || !shouldReconnect()) {
                return;
            }

            reconnectAttempt += 1;
            options?.onReconnectAttempt?.(reconnectAttempt);
            const backoff = Math.min(
                reconnectDelayMs * Math.pow(2, reconnectAttempt - 1),
                maxReconnectDelayMs,
            );
            reconnectTimer = window.setTimeout(connect, backoff);
        };
    };

    const connect = () => {
        if (closed) return;
        source = new EventSource(`${API_BASE}/api/goals/${goalId}/stream`);
        attachListeners(source);
    };

    connect();

    return {
        close: () => {
            closed = true;
            if (reconnectTimer !== null) {
                window.clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            source?.close();
        },
    };
}
