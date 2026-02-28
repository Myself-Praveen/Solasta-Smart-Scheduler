"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  createGoal,
  streamGoalEventsWithReconnect,
  getGoalLogs,
  type Step,
  type Plan,
  type AgentLog,
  type StreamEventData,
} from "./api";

import html2canvas from "html2canvas";
import jsPDF from "jspdf";

// ── Status helpers ───────────────────────────────────────────

function statusIcon(status: string): string {
  const icons: Record<string, string> = {
    pending: "⏳",
    in_progress: "⚡",
    evaluating: "🔍",
    completed: "✅",
    failed: "❌",
    skipped: "⏭️",
    replanned: "🔄",
    retrying: "🔁",
  };
  return icons[status] || "•";
}

function badgeClass(status: string): string {
  const map: Record<string, string> = {
    pending: "badge badge-pending",
    in_progress: "badge badge-in-progress",
    evaluating: "badge badge-evaluating",
    completed: "badge badge-completed",
    failed: "badge badge-failed",
    skipped: "badge badge-pending",
    replanned: "badge badge-replanning",
    retrying: "badge badge-evaluating",
  };
  return map[status] || "badge badge-pending";
}

// ── Types ────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  timestamp: Date;
  type?: "text" | "plan" | "step_update" | "replan" | "error" | "complete";
}

interface GoalHistoryItem {
  id: string;
  raw_input: string;
  status: string;
  created_at: string;
}

// ── Page Component ───────────────────────────────────────────

export default function Home() {
  const [goalInput, setGoalInput] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [goalId, setGoalId] = useState<string | null>(null);
  const [goalStatus, setGoalStatus] = useState<string>("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [planVersion, setPlanVersion] = useState(1);
  const [expandedStep, setExpandedStep] = useState<string | null>(null);
  const [goalHistory, setGoalHistory] = useState<GoalHistoryItem[]>([]);
  const [showSidebar, setShowSidebar] = useState(true);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<{ close: () => void } | null>(null);
  const lastFailedStepIdRef = useRef<string | null>(null);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  // Fetch goal history on mount 
  useEffect(() => {
    fetchGoalHistory();
  }, []);

  const fetchGoalHistory = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/goals");
      if (res.ok) {
        const goals = await res.json();
        setGoalHistory(goals.map((g: any) => ({
          id: g.id,
          raw_input: g.raw_input,
          status: g.status,
          created_at: g.created_at,
        })));
      }
    } catch {
      // Silently fail — history is optional
    }
  };

  const addChat = useCallback((role: "user" | "agent" | "system", content: string, type: ChatMessage["type"] = "text") => {
    setChatMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role, content, timestamp: new Date(), type },
    ]);
  }, []);

  const handleSubmitGoal = async () => {
    if (!goalInput.trim() || isProcessing) return;

    setIsProcessing(true);
    setGoalStatus("received");
    setSteps([]);
    setPlan(null);
    setChatMessages([]);
    setLogs([]);
    setPlanVersion(1);
    setExpandedStep(null);
    lastFailedStepIdRef.current = null;
    addChat("user", goalInput);
    addChat("agent", "🎯 Goal received. Starting autonomous processing...", "text");

    try {
      const response = await createGoal({ user_input: goalInput });
      setGoalId(response.goal_id);
      addChat("agent", `📋 Goal registered (ID: ${response.goal_id.slice(0, 8)}…). Initiating planning phase...`, "text");

      // Start SSE stream
      eventSourceRef.current?.close();
      const source = streamGoalEventsWithReconnect(
        response.goal_id,
        (eventType: string, data: StreamEventData) => {
          handleStreamEvent(eventType, data);
        },
        () => {
          addChat("system", "⚠️ Connection interrupted. Reconnecting...", "error");
        },
        {
          shouldReconnect: () => isProcessing,
          onReconnectAttempt: (attempt) => {
            addChat("system", `🔌 Reconnect attempt ${attempt}...`, "text");
          },
        },
      );
      eventSourceRef.current = source;
    } catch (err) {
      addChat("agent", `❌ Failed to submit goal: ${err}`, "error");
      setIsProcessing(false);
    }
  };

  const handleStreamEvent = (eventType: string, data: StreamEventData) => {
    switch (eventType) {
      case "goal_status":
        setGoalStatus(data.status || "");
        addChat("agent", `🔄 ${data.message || `Status updated: ${data.status}`}`, "text");
        break;

      case "plan_created":
        if (data.steps) {
          const failedStepId = lastFailedStepIdRef.current;
          const normalizedSteps = data.steps.map((step) => {
            if (data.message && failedStepId && step.step_id === failedStepId && step.status === "pending") {
              return { ...step, status: "replanned" };
            }
            return step;
          });

          setPlan({
            id: data.plan_id || "",
            goal_id: goalId || "",
            version: data.version || 1,
            is_active: true,
            steps: normalizedSteps,
            created_at: new Date().toISOString(),
          });
          setSteps(normalizedSteps);
          setPlanVersion(data.version || 1);
        }
        const stepNames = data.steps?.map(s => s.title).join(", ") || "";
        addChat("agent", `📊 Plan ${data.message ? "updated" : "created"} (v${data.version}) with ${data.steps?.length || 0} steps: ${stepNames}`, "plan");
        break;

      case "step_update":
        setSteps((prev) =>
          prev.map((s) =>
            s.step_id === data.step_id
              ? {
                ...s,
                status: data.status || s.status,
                error_message: data.error ?? s.error_message,
              }
              : s,
          ),
        );
        const stepTitle = data.title || data.step_id;
        if (data.status === "in_progress") {
          addChat("agent", `⚡ Executing: ${stepTitle}`, "step_update");
        } else if (data.status === "evaluating") {
          addChat("agent", `🔍 Evaluating results: ${stepTitle}`, "step_update");
        } else if (data.status === "completed") {
          addChat("agent", `✅ Completed: ${stepTitle}`, "step_update");
        } else if (data.status === "failed") {
          if (data.step_id) lastFailedStepIdRef.current = data.step_id;
          addChat("agent", `❌ Failed: ${stepTitle} — ${data.error || ""}`, "error");
        } else if (data.status === "retrying") {
          addChat("agent", `🔁 Retrying: ${stepTitle} (attempt ${data.retry_count})`, "step_update");
        }
        break;

      case "replanning":
        addChat("agent", `🧠 Adaptive Replanning: ${data.message || "Generating recovery plan..."}`, "replan");
        setGoalStatus("replanning");
        if (lastFailedStepIdRef.current) {
          const failedStepId = lastFailedStepIdRef.current;
          setSteps((prev) =>
            prev.map((s) =>
              s.step_id === failedStepId && s.status === "failed"
                ? { ...s, status: "replanned" }
                : s,
            ),
          );
        }
        break;

      case "goal_completed":
        setGoalStatus("completed");
        setIsProcessing(false);
        addChat("agent", "🎉 All steps completed successfully! Your study schedule is ready.", "complete");
        eventSourceRef.current?.close();
        fetchGoalHistory(); // Refresh sidebar
        break;

      case "goal_failed":
        setGoalStatus("failed");
        setIsProcessing(false);
        addChat("agent", `💥 ${data.message || "Goal could not be completed."}`, "error");
        eventSourceRef.current?.close();
        break;

      case "error":
        addChat("agent", `⚠️ ${data.error || data.message}`, "error");
        break;

      case "heartbeat":
        break;
    }
  };

  const fetchLogs = async () => {
    if (!goalId) return;
    try {
      const fetchedLogs = await getGoalLogs(goalId);
      setLogs(fetchedLogs);
      setShowLogs(true);
    } catch {
      addChat("system", "Failed to fetch agent logs", "error");
    }
  };

  // ── Render ─────────────────────────────────────────────────

  const completedSteps = steps.filter((s) => s.status === "completed").length;
  const progress = steps.length > 0 ? (completedSteps / steps.length) * 100 : 0;

  return (
    <div style={{ position: "relative", zIndex: 1, minHeight: "100vh", display: "flex" }}>

      {/* ── Left Sidebar: Chat History ────────────────────── */}
      {showSidebar && (
        <aside
          style={{
            width: "260px",
            minWidth: "260px",
            borderRight: "1px solid var(--border)",
            background: "rgba(10, 10, 15, 0.9)",
            display: "flex",
            flexDirection: "column",
            height: "100vh",
            position: "sticky",
            top: 0,
          }}
        >
          <div style={{ padding: "20px 16px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
              <div
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "10px",
                  background: "linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "16px",
                }}
              >
                🧠
              </div>
              <div>
                <h1 style={{ fontSize: "1rem", fontWeight: 700, letterSpacing: "-0.02em" }}>Solasta</h1>
                <p style={{ fontSize: "0.6rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
                  Smart Study Agent
                </p>
              </div>
            </div>
          </div>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
            <p style={{ fontSize: "0.7rem", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 600, letterSpacing: "0.05em" }}>
              📂 Past Sessions ({goalHistory.length})
            </p>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
            {goalHistory.length === 0 ? (
              <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", padding: "12px 8px", textAlign: "center" }}>
                No past sessions yet. Submit your first goal!
              </p>
            ) : (
              goalHistory.map((g) => (
                <div
                  key={g.id}
                  style={{
                    padding: "10px 12px",
                    borderRadius: "8px",
                    marginBottom: "4px",
                    fontSize: "0.78rem",
                    color: "var(--text-secondary)",
                    background: g.id === goalId ? "rgba(108, 99, 255, 0.12)" : "transparent",
                    borderLeft: g.id === goalId ? "3px solid var(--accent-primary)" : "3px solid transparent",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                  onMouseEnter={(e) => { if (g.id !== goalId) (e.currentTarget.style.background = "rgba(108, 99, 255, 0.06)"); }}
                  onMouseLeave={(e) => { if (g.id !== goalId) (e.currentTarget.style.background = "transparent"); }}
                >
                  <p style={{ fontWeight: 500, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {g.raw_input}
                  </p>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: "4px", fontSize: "0.65rem", color: "var(--text-muted)" }}>
                    <span className={badgeClass(g.status)} style={{ padding: "1px 6px", fontSize: "0.6rem" }}>{g.status}</span>
                    <span>{new Date(g.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>
      )}

      {/* ── Main Content ──────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100vh" }}>

        {/* ── Header ──────────────────────────────────────── */}
        <header
          style={{
            padding: "12px 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: "1px solid var(--border)",
            background: "rgba(10, 10, 15, 0.8)",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              onClick={() => setShowSidebar(!showSidebar)}
              style={{
                background: "none",
                border: "1px solid var(--border)",
                color: "var(--text-secondary)",
                padding: "6px 10px",
                borderRadius: "6px",
                cursor: "pointer",
                fontSize: "0.85rem",
              }}
            >
              {showSidebar ? "◀" : "▶"}
            </button>
            {goalStatus && (
              <span className={badgeClass(goalStatus)}>
                {statusIcon(goalStatus)} {goalStatus}
              </span>
            )}
            {steps.length > 0 && (
              <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                Plan v{planVersion} • {completedSteps}/{steps.length} steps
              </span>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {goalId && (
              <button
                onClick={fetchLogs}
                style={{
                  background: "transparent",
                  border: "1px solid var(--border)",
                  color: "var(--text-secondary)",
                  padding: "6px 14px",
                  borderRadius: "8px",
                  fontSize: "0.78rem",
                  cursor: "pointer",
                }}
              >
                📊 Agent Logs
              </button>
            )}
          </div>
        </header>

        {/* ── Chat + Plan Row ─────────────────────────── */}
        <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0 }}>

          {/* ── Chat Panel ────────────────────────────────── */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>

            {/* Chat Messages */}
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
              {chatMessages.length === 0 && !isProcessing && (
                <div style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                  gap: "16px",
                  opacity: 0.6,
                }}>
                  <div style={{ fontSize: "4rem" }}>🎓</div>
                  <p style={{ fontSize: "1.2rem", fontWeight: 600, color: "var(--text-primary)" }}>
                    What would you like to study?
                  </p>
                  <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", maxWidth: "480px", textAlign: "center", lineHeight: 1.6 }}>
                    I&apos;ll autonomously decompose your goal, build a multi-step plan,
                    execute each step, and adapt if anything fails — all in real time.
                  </p>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", justifyContent: "center", marginTop: "8px" }}>
                    {["Plan my GATE exam schedule for 3 months", "Study plan for SAT in 8 weeks", "UPSC preparation schedule for 6 months"].map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => setGoalInput(suggestion)}
                        style={{
                          background: "rgba(108, 99, 255, 0.08)",
                          border: "1px solid var(--border)",
                          color: "var(--text-secondary)",
                          padding: "8px 14px",
                          borderRadius: "20px",
                          fontSize: "0.78rem",
                          cursor: "pointer",
                          transition: "all 0.2s",
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent-primary)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {chatMessages.map((msg) => (
                <div
                  key={msg.id}
                  className="animate-fade-in"
                  style={{
                    display: "flex",
                    justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                    marginBottom: "12px",
                  }}
                >
                  <div
                    style={{
                      maxWidth: "80%",
                      padding: "12px 16px",
                      borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                      background: msg.role === "user"
                        ? "linear-gradient(135deg, var(--accent-primary), #8b7cf7)"
                        : msg.type === "error"
                          ? "rgba(248, 113, 113, 0.12)"
                          : msg.type === "replan"
                            ? "rgba(251, 191, 36, 0.1)"
                            : msg.type === "complete"
                              ? "rgba(52, 211, 153, 0.1)"
                              : "var(--glass)",
                      border: msg.role === "user"
                        ? "none"
                        : msg.type === "error"
                          ? "1px solid rgba(248, 113, 113, 0.2)"
                          : msg.type === "replan"
                            ? "1px solid rgba(251, 191, 36, 0.2)"
                            : msg.type === "complete"
                              ? "1px solid rgba(52, 211, 153, 0.2)"
                              : "1px solid var(--border)",
                      fontSize: "0.88rem",
                      lineHeight: 1.6,
                      color: msg.role === "user" ? "#fff" : "var(--text-primary)",
                    }}
                  >
                    {msg.role === "agent" && (
                      <span style={{ fontSize: "0.65rem", color: "var(--accent-secondary)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", display: "block", marginBottom: "4px" }}>
                        🤖 Agent
                      </span>
                    )}
                    {msg.content}
                    <div style={{ fontSize: "0.65rem", color: msg.role === "user" ? "rgba(255,255,255,0.6)" : "var(--text-muted)", marginTop: "4px" }}>
                      {msg.timestamp.toLocaleTimeString()}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Chat Input */}
            <div style={{
              padding: "16px 24px",
              borderTop: "1px solid var(--border)",
              background: "rgba(10, 10, 15, 0.9)",
            }}>
              <div style={{ display: "flex", gap: "10px" }}>
                <input
                  className="chat-input"
                  placeholder='Type your study goal... e.g. "Plan my GATE schedule for 3 months"'
                  value={goalInput}
                  onChange={(e) => setGoalInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSubmitGoal()}
                  disabled={isProcessing}
                  style={{ borderRadius: "24px", padding: "12px 20px" }}
                />
                <button
                  className="btn-primary"
                  onClick={handleSubmitGoal}
                  disabled={isProcessing || !goalInput.trim()}
                  style={{ borderRadius: "24px", padding: "12px 24px" }}
                >
                  {isProcessing ? (
                    <>
                      <div className="spinner" /> Processing
                    </>
                  ) : (
                    "🚀 Send"
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* ── Right Panel: Execution Plan + Progress ────── */}
          {steps.length > 0 && (
            <aside
              style={{
                width: "380px",
                minWidth: "380px",
                borderLeft: "1px solid var(--border)",
                background: "rgba(10, 10, 15, 0.6)",
                display: "flex",
                flexDirection: "column",
                overflowY: "auto",
              }}
            >
              {/* Progress Bar */}
              <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                  <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>
                    📋 Execution Plan v{planVersion}
                  </span>
                  <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                    {completedSteps}/{steps.length}
                  </span>
                </div>
                <div style={{ height: "4px", borderRadius: "2px", background: "var(--bg-card)", overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${progress}%`,
                      borderRadius: "2px",
                      background: "linear-gradient(90deg, var(--accent-primary), var(--success))",
                      transition: "width 0.6s ease",
                    }}
                  />
                </div>
                {goalStatus === "completed" && (
                  <>
                    <button
                      onClick={async () => {
                        try {
                          let finalPlan = plan;
                          if (goalId) {
                            const { getPlan } = await import("./api");
                            finalPlan = await getPlan(goalId);
                          }
                          let scheduleData: any = null;
                          if (finalPlan && finalPlan.steps) {
                            for (const s of finalPlan.steps) {
                              if (s.result_payload && s.result_payload.output_data) {
                                if (Object.keys(s.result_payload.output_data).length > 0) {
                                  scheduleData = Object.assign(scheduleData || {}, s.result_payload.output_data);
                                }
                              }
                            }
                          }
                          const container = document.createElement("div");
                          container.style.position = "absolute";
                          container.style.left = "-9999px";
                          container.style.width = "800px";
                          container.style.padding = "40px";
                          container.style.background = "#fff";
                          container.style.color = "#000";
                          container.style.fontFamily = "system-ui, sans-serif";

                          let contentHtml = `
                            <div style="border-bottom: 2px solid #ccc; padding-bottom: 20px; margin-bottom: 30px;">
                              <h1 style="font-size: 28px; margin: 0; color: #111;">Solasta Smart Study Schedule</h1>
                              <p style="color: #666; margin-top: 8px;">Generated on: ${new Date().toLocaleDateString()}</p>
                              <p style="font-weight: 600; font-size: 16px; margin-top: 12px; padding: 10px; background: #f5f5f5; border-radius: 6px;">Goal: ${goalInput}</p>
                            </div>
                          `;
                          if (scheduleData && Object.keys(scheduleData).length > 0) {
                            contentHtml += `<div style="font-size: 12px; line-height: 1.4;">`;
                            if (scheduleData.schedule && Array.isArray(scheduleData.schedule)) {
                              contentHtml += `<h2 style="font-size: 18px; margin: 0 0 10px 0;">Weekly Schedule</h2>`;
                              scheduleData.schedule.forEach((w: any) => {
                                contentHtml += `<div style="margin-bottom: 12px; border: 1px solid #ddd; padding: 8px; border-radius: 4px; page-break-inside: avoid;">`;
                                contentHtml += `<h3 style="margin: 0 0 6px 0; font-size: 14px; color: #333;">Week ${w.week} (${w.start_date} to ${w.end_date})</h3>`;
                                contentHtml += `<div style="display: flex; flex-wrap: wrap; gap: 8px;">`;
                                if (Array.isArray(w.days)) {
                                  w.days.forEach((d: any) => {
                                    contentHtml += `<div style="flex: 1; min-width: 110px; background: #fafafa; padding: 6px; border-radius: 4px; border: 1px solid #eee;">`;
                                    contentHtml += `<strong style="display: block; font-size: 11px; margin-bottom: 4px; color: #555;">${d.day}</strong>`;
                                    if (Array.isArray(d.sessions)) {
                                      d.sessions.forEach((s: any) => {
                                        contentHtml += `<div style="font-size: 10px; padding: 3px; background: #eef2ff; color: #3730a3; margin-bottom: 3px; border-radius: 3px;"><b>${s.time_slot}</b><br/>${s.subject}</div>`;
                                      });
                                    }
                                    contentHtml += `</div>`;
                                  });
                                }
                                contentHtml += `</div></div>`;
                              });
                              delete scheduleData.schedule;
                            }
                            const renderData = (obj: any, level = 0): string => {
                              if (typeof obj === 'string') return `<p style="margin: 0 0 4px 0;">${obj}</p>`;
                              if (Array.isArray(obj)) return `<ul style="margin: 2px 0 8px 16px; padding: 0;">` + obj.map(item => `<li style="margin-bottom: 2px;">${renderData(item, level + 1)}</li>`).join('') + `</ul>`;
                              if (typeof obj === 'object' && obj !== null) {
                                return Object.entries(obj).map(([k, v]) => {
                                  const cleanKey = k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                                  return `<div style="margin-bottom: ${level === 0 ? '10px' : '4px'}; page-break-inside: avoid;"><strong style="color: #444; font-size: ${level === 0 ? '14px' : '12px'}; display: block; margin-bottom: 2px; border-bottom: ${level === 0 ? '1px solid #eee' : 'none'}; padding-bottom: ${level === 0 ? '2px' : '0'};">${cleanKey}:</strong><div style="padding-left: ${level === 0 ? '0' : '12px'};">${renderData(v, level + 1)}</div></div>`;
                                }).join('');
                              }
                              return String(obj);
                            };
                            contentHtml += renderData(scheduleData);
                            contentHtml += `</div>`;
                          } else {
                            contentHtml += `<div style="padding: 20px; background: #f9f9f9; border: 1px dashed #ccc; text-align: center;">Schedule data is being compiled.</div>`;
                          }
                          container.innerHTML = contentHtml;
                          document.body.appendChild(container);
                          const canvas = await html2canvas(container, { scale: 2, useCORS: true, backgroundColor: "#ffffff", windowWidth: 800 });
                          document.body.removeChild(container);
                          const imgData = canvas.toDataURL("image/jpeg", 1.0);
                          const pdf = new jsPDF("p", "pt", "a4");
                          const pdfWidth = pdf.internal.pageSize.getWidth();
                          const pdfHeight = (canvas.height * pdfWidth) / canvas.width;
                          let heightLeft = pdfHeight;
                          let position = 0;
                          const pageHeight = pdf.internal.pageSize.getHeight();
                          pdf.addImage(imgData, "JPEG", 0, position, pdfWidth, pdfHeight);
                          heightLeft -= pageHeight;
                          while (heightLeft >= 0) {
                            position = heightLeft - pdfHeight;
                            pdf.addPage();
                            pdf.addImage(imgData, "JPEG", 0, position, pdfWidth, pdfHeight);
                            heightLeft -= pageHeight;
                          }
                          pdf.save("Solasta_Study_Schedule.pdf");
                        } catch (err) {
                          console.error("Failed to generate PDF", err);
                        }
                      }}
                      style={{
                        marginTop: "10px",
                        width: "100%",
                        background: "linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))",
                        border: "none",
                        color: "white",
                        padding: "8px",
                        borderRadius: "8px",
                        fontSize: "0.82rem",
                        fontWeight: 600,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "6px",
                      }}
                    >
                      📄 Download PDF
                    </button>

                    {/* ── .ics Calendar Export Button ───── */}
                    <button
                      onClick={async () => {
                        try {
                          let finalPlan = plan;
                          if (goalId) {
                            const { getPlan } = await import("./api");
                            finalPlan = await getPlan(goalId);
                          }
                          let scheduleData: any = null;
                          if (finalPlan && finalPlan.steps) {
                            for (const s of finalPlan.steps) {
                              if (s.result_payload && s.result_payload.output_data) {
                                if (Object.keys(s.result_payload.output_data).length > 0) {
                                  scheduleData = Object.assign(scheduleData || {}, s.result_payload.output_data);
                                }
                              }
                            }
                          }

                          // Generate .ics content
                          const pad = (n: number) => String(n).padStart(2, "0");
                          const toICSDate = (date: Date) => {
                            return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}T${pad(date.getHours())}${pad(date.getMinutes())}00`;
                          };

                          let icsContent = [
                            "BEGIN:VCALENDAR",
                            "VERSION:2.0",
                            "PRODID:-//Solasta Smart Study Agent//EN",
                            "CALSCALE:GREGORIAN",
                            "METHOD:PUBLISH",
                            "X-WR-CALNAME:Solasta Study Schedule",
                          ].join("\r\n");

                          let eventCount = 0;
                          const timeSlotToHour = (slot: string): number => {
                            const match = slot.match(/(\d+)/);
                            if (match) return parseInt(match[1]);
                            const slots: Record<string, number> = { "morning": 9, "afternoon": 14, "evening": 18, "night": 20 };
                            const lower = slot.toLowerCase();
                            for (const [k, v] of Object.entries(slots)) {
                              if (lower.includes(k)) return v;
                            }
                            return 9 + eventCount;
                          };

                          if (scheduleData?.schedule && Array.isArray(scheduleData.schedule)) {
                            for (const week of scheduleData.schedule) {
                              if (!Array.isArray(week.days)) continue;
                              for (const day of week.days) {
                                if (!Array.isArray(day.sessions)) continue;
                                for (const session of day.sessions) {
                                  // Parse the start date from week data
                                  let startDate = new Date();
                                  try {
                                    if (week.start_date) startDate = new Date(week.start_date);
                                  } catch { /* use today */ }

                                  // Map day name to offset
                                  const dayNames = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
                                  const dayIdx = dayNames.indexOf((day.day || "").toLowerCase());
                                  if (dayIdx >= 0) {
                                    const currentDay = startDate.getDay();
                                    const diff = (dayIdx - currentDay + 7) % 7;
                                    startDate = new Date(startDate.getTime() + diff * 86400000);
                                  }

                                  const hour = timeSlotToHour(session.time_slot || "09:00");
                                  startDate.setHours(hour, 0, 0, 0);
                                  const endDate = new Date(startDate.getTime() + 90 * 60000); // 90 min sessions

                                  const uid = `solasta-${Date.now()}-${eventCount}@solasta.local`;
                                  icsContent += "\r\n" + [
                                    "BEGIN:VEVENT",
                                    `UID:${uid}`,
                                    `DTSTART:${toICSDate(startDate)}`,
                                    `DTEND:${toICSDate(endDate)}`,
                                    `SUMMARY:📚 ${session.subject || "Study Session"}`,
                                    `DESCRIPTION:${session.time_slot || ""} — ${session.subject || "Study"} (Week ${week.week || "?"})\\nGenerated by Solasta Smart Study Agent`,
                                    `LOCATION:Study Desk`,
                                    "STATUS:CONFIRMED",
                                    "END:VEVENT",
                                  ].join("\r\n");
                                  eventCount++;
                                }
                              }
                            }
                          }

                          // If no schedule data, create placeholder events from steps
                          if (eventCount === 0) {
                            const base = new Date();
                            base.setHours(9, 0, 0, 0);
                            const stepTitles = finalPlan?.steps?.map(s => s.title) || ["Study Session"];
                            for (let i = 0; i < stepTitles.length; i++) {
                              const start = new Date(base.getTime() + i * 86400000);
                              const end = new Date(start.getTime() + 60 * 60000);
                              icsContent += "\r\n" + [
                                "BEGIN:VEVENT",
                                `UID:solasta-fallback-${i}@solasta.local`,
                                `DTSTART:${toICSDate(start)}`,
                                `DTEND:${toICSDate(end)}`,
                                `SUMMARY:📚 ${stepTitles[i]}`,
                                `DESCRIPTION:Generated by Solasta Smart Study Agent`,
                                "STATUS:CONFIRMED",
                                "END:VEVENT",
                              ].join("\r\n");
                              eventCount++;
                            }
                          }

                          icsContent += "\r\nEND:VCALENDAR";

                          // Trigger download
                          const blob = new Blob([icsContent], { type: "text/calendar;charset=utf-8" });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = "Solasta_Study_Schedule.ics";
                          document.body.appendChild(a);
                          a.click();
                          document.body.removeChild(a);
                          URL.revokeObjectURL(url);
                        } catch (err) {
                          console.error("Failed to generate calendar", err);
                        }
                      }}
                      style={{
                        marginTop: "6px",
                        width: "100%",
                        background: "linear-gradient(135deg, #34d399, #059669)",
                        border: "none",
                        color: "white",
                        padding: "8px",
                        borderRadius: "8px",
                        fontSize: "0.82rem",
                        fontWeight: 600,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "6px",
                      }}
                    >
                      📅 Add to Calendar (.ics)
                    </button>
                  </>
                )}
              </div>

              {/* Steps List */}
              <div style={{ flex: 1, padding: "12px 16px" }}>
                <div className="step-timeline">
                  {steps.map((step, idx) => (
                    <div
                      key={step.step_id}
                      className={`step-node ${step.status}`}
                      style={{ animationDelay: `${idx * 80}ms` }}
                    >
                      <div
                        className="glass-card"
                        style={{ padding: "12px 14px", marginBottom: "4px", borderRadius: "10px", cursor: "pointer" }}
                        onClick={() => setExpandedStep(expandedStep === step.step_id ? null : step.step_id)}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                          <span style={{ fontWeight: 600, fontSize: "0.82rem" }}>
                            {statusIcon(step.status)} {step.title}
                          </span>
                          <span className={badgeClass(step.status)} style={{ fontSize: "0.6rem", padding: "2px 6px" }}>{step.status}</span>
                        </div>
                        <p style={{ fontSize: "0.72rem", color: "var(--text-secondary)", lineHeight: 1.4 }}>
                          {step.description}
                        </p>

                        {/* Tool Tags */}
                        <div style={{ display: "flex", gap: "4px", marginTop: "6px", flexWrap: "wrap" }}>
                          {step.required_tools.map((tool) => (
                            <span
                              key={tool}
                              style={{
                                fontSize: "0.6rem",
                                padding: "1px 6px",
                                borderRadius: "4px",
                                background: "rgba(108, 99, 255, 0.1)",
                                color: "var(--accent-secondary)",
                                border: "1px solid rgba(108, 99, 255, 0.15)",
                              }}
                            >
                              {tool}
                            </span>
                          ))}

                          {/* Brain Button */}
                          <button
                            onClick={(e) => { e.stopPropagation(); setExpandedStep(expandedStep === step.step_id ? null : step.step_id); }}
                            style={{
                              fontSize: "0.6rem",
                              padding: "1px 8px",
                              borderRadius: "4px",
                              background: expandedStep === step.step_id ? "rgba(108, 99, 255, 0.3)" : "rgba(52, 211, 153, 0.1)",
                              color: expandedStep === step.step_id ? "var(--accent-primary)" : "var(--success)",
                              border: `1px solid ${expandedStep === step.step_id ? "var(--accent-primary)" : "rgba(52, 211, 153, 0.2)"}`,
                              cursor: "pointer",
                              fontWeight: 700,
                            }}
                          >
                            🧠 {expandedStep === step.step_id ? "Hide Brain" : "View Brain"}
                          </button>
                        </div>

                        {/* ── Expanded Thought Process Panel ───── */}
                        {expandedStep === step.step_id && (
                          <div
                            className="animate-slide-in"
                            style={{
                              marginTop: "10px",
                              padding: "12px",
                              borderRadius: "8px",
                              background: "rgba(108, 99, 255, 0.06)",
                              border: "1px solid rgba(108, 99, 255, 0.15)",
                            }}
                          >
                            <h4 style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--accent-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "8px" }}>
                              🧠 Agent Thought Process
                            </h4>

                            {step.thought_process && (
                              <div style={{ marginBottom: "8px" }}>
                                <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", fontWeight: 600 }}>Chain-of-Thought:</span>
                                <p style={{ fontSize: "0.78rem", color: "var(--text-primary)", marginTop: "2px", lineHeight: 1.5, padding: "6px 8px", background: "rgba(108, 99, 255, 0.05)", borderRadius: "4px" }}>
                                  💭 {step.thought_process}
                                </p>
                              </div>
                            )}

                            <div style={{ marginBottom: "8px" }}>
                              <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", fontWeight: 600 }}>Expected Outcome:</span>
                              <p style={{ fontSize: "0.75rem", color: "var(--success)", marginTop: "2px" }}>
                                🎯 {step.expected_outcome}
                              </p>
                            </div>

                            <div style={{ marginBottom: "8px" }}>
                              <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", fontWeight: 600 }}>Priority:</span>
                              <span className={`badge ${step.priority === "high" ? "badge-failed" : step.priority === "medium" ? "badge-evaluating" : "badge-pending"}`} style={{ marginLeft: "6px", fontSize: "0.6rem", padding: "1px 6px" }}>
                                {step.priority}
                              </span>
                            </div>

                            {step.depends_on && step.depends_on.length > 0 && (
                              <div style={{ marginBottom: "8px" }}>
                                <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", fontWeight: 600 }}>Dependencies:</span>
                                <div style={{ display: "flex", gap: "4px", marginTop: "2px", flexWrap: "wrap" }}>
                                  {step.depends_on.map((dep) => (
                                    <span key={dep} style={{
                                      fontSize: "0.6rem", padding: "1px 6px", borderRadius: "4px",
                                      background: "rgba(96, 165, 250, 0.1)", color: "var(--info)", border: "1px solid rgba(96, 165, 250, 0.2)"
                                    }}>
                                      ↳ {dep}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}

                            <div>
                              <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", fontWeight: 600 }}>Tools Used:</span>
                              <div style={{ display: "flex", gap: "4px", marginTop: "2px", flexWrap: "wrap" }}>
                                {step.required_tools.map((tool) => (
                                  <span key={tool} style={{
                                    fontSize: "0.6rem", padding: "2px 8px", borderRadius: "4px",
                                    background: "rgba(52, 211, 153, 0.1)", color: "var(--success)", border: "1px solid rgba(52, 211, 153, 0.2)"
                                  }}>
                                    ⚙️ {tool}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                        )}

                        {step.error_message && (
                          <div style={{
                            marginTop: "6px",
                            padding: "6px 10px",
                            borderRadius: "6px",
                            background: "rgba(248, 113, 113, 0.1)",
                            borderLeft: "3px solid var(--error)",
                            fontSize: "0.72rem",
                            color: "var(--error)",
                          }}>
                            ⚠️ {step.error_message}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          )}
        </div>
      </div>

      {/* ── Agent Logs Modal ────────────────────────────── */}
      {showLogs && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.7)",
            backdropFilter: "blur(4px)",
            zIndex: 200,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "40px",
          }}
          onClick={() => setShowLogs(false)}
        >
          <div
            className="glass-card animate-slide-in"
            style={{
              maxWidth: "900px",
              width: "100%",
              maxHeight: "80vh",
              overflow: "auto",
              padding: "28px",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
              <h2 style={{ fontSize: "1.1rem", fontWeight: 700 }}>📊 Agent Execution Logs</h2>
              <button
                onClick={() => setShowLogs(false)}
                style={{ background: "none", border: "none", color: "var(--text-muted)", fontSize: "1.5rem", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>

            {logs.length === 0 ? (
              <p style={{ color: "var(--text-muted)" }}>No logs available yet.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {logs.map((log) => (
                  <div
                    key={log.id}
                    style={{
                      padding: "14px 18px",
                      borderRadius: "10px",
                      background: "var(--bg-card)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                      <span className={`badge ${log.agent_type === "planner" ? "badge-in-progress" : log.agent_type === "executor" ? "badge-evaluating" : log.agent_type === "evaluator" ? "badge-completed" : "badge-replanning"}`}>
                        {log.agent_type}
                      </span>
                      <div style={{ display: "flex", gap: "12px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                        <span>🤖 {log.provider}/{log.model}</span>
                        <span>⏱️ {log.latency_ms}ms</span>
                        <span>📥 {log.tokens_in} / 📤 {log.tokens_out}</span>
                      </div>
                    </div>
                    <p style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                      {log.response_summary.slice(0, 200)}
                      {log.response_summary.length > 200 ? "…" : ""}
                    </p>
                    {log.error && (
                      <p style={{ fontSize: "0.8rem", color: "var(--error)", marginTop: "6px" }}>
                        ⚠️ {log.error}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
