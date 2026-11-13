import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { SeverityBadge } from "../components/Severity";
import { ErrorBox } from "../components/States";
import { api } from "../lib/api";
import { useAnnounceAnalysis, useCurrentAnalysis } from "../lib/current";
import { categoryLabel } from "../lib/format";
import { useApi } from "../lib/hooks";
import type { ChatFindingRef, ChatMessage } from "../lib/types";

interface MessageItem extends ChatMessage {
  id: string;
  provider?: string;
  referencedFindings?: ChatFindingRef[];
  suggestedQuestions?: string[];
  timestamp: string;
}

export function ChatbotPage() {
  const params = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { analysisId: contextAnalysisId } = useCurrentAnalysis();
  const analysisId = params.analysisId || contextAnalysisId || "";
  const findingId = searchParams.get("finding_id") || "";

  useAnnounceAnalysis(analysisId || null);

  const [inputQuery, setInputQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Fetch focused finding if finding_id is in query params
  const focusedFinding = useApi(
    () => (findingId ? api.finding(findingId).catch(() => null) : Promise.resolve(null)),
    [findingId],
  );

  // Fetch analysis summary for context pill counters
  const summaryApi = useApi(
    () => (analysisId ? api.summary(analysisId).catch(() => null) : Promise.resolve(null)),
    [analysisId],
  );

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  // Set default initial greeting when page loads
  useEffect(() => {
    if (messages.length === 0) {
      if (focusedFinding.data) {
        const f = focusedFinding.data;
        setMessages([
          {
            id: "init-focused",
            role: "assistant",
            content: `Hello! I am your **RepoVue AI Assistant**. You are currently focusing on finding:\n\n**${f.title}** (${f.severity.toUpperCase()} · ${categoryLabel(f.category)})\n*File*: \`${f.path}:${f.start_line}\`\n\nAsk me anything about why this occurred, how to patch it safely, or how it affects runtime security and performance.`,
            suggestedQuestions: [
              `Why does "${f.title.slice(0, 40)}..." happen?`,
              "Explain the root cause and blast radius in simple words",
              "Show me the exact fix for this finding",
              "What other files might suffer from the same pattern?",
            ],
            timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            provider: "RepoVue Assistant",
          },
        ]);
      } else {
        setMessages([
          {
            id: "init-general",
            role: "assistant",
            content: `Welcome to the **RepoVue Finding Assistant & Chatbot**!\n\nI am grounded in all static analysis findings, rule violations, AST metrics, and generated patches for this repository. You can ask me to explain any vulnerability, compare issues, prioritize fixes, or write concrete remediation plans.`,
            suggestedQuestions: [
              "What are the most critical vulnerabilities in this repo?",
              "Summarize all performance bottlenecks and slow loops",
              "Generate a step-by-step remediation plan for my team",
              "Which logical bugs are most likely to crash in production?",
            ],
            timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            provider: "RepoVue Assistant",
          },
        ]);
      }
    }
  }, [focusedFinding.data]);

  const handleSend = async (queryToSend?: string) => {
    const query = (queryToSend ?? inputQuery).trim();
    if (!query || loading) return;

    setInputQuery("");
    setChatError(null);

    const userMsg: MessageItem = {
      id: `u-${Date.now()}`,
      role: "user",
      content: query,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setLoading(true);

    try {
      // Build history for backend LLM
      const historyPayload = nextMessages.slice(-6).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const res = await api.chat({
        query,
        analysis_id: analysisId || null,
        finding_id: findingId || null,
        history: historyPayload,
      });

      const assistantMsg: MessageItem = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: res.response,
        provider: res.provider,
        referencedFindings: res.referenced_findings,
        suggestedQuestions: res.suggested_questions,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      setChatError(err?.message || "Failed to reach AI doctor service. Please try again.");
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClearHistory = () => {
    setMessages([]);
  };

  const clearFocusedFinding = () => {
    searchParams.delete("finding_id");
    setSearchParams(searchParams);
  };

  return (
    <div className="rv-pad" style={{ padding: "24px 32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      {/* Header */}
      <header style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
          <div>
            <div className="mono" style={{ fontSize: 12, color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Sidebar 08 · AI Finding Chatbot
            </div>
            <h1 style={{ margin: "6px 0 0", fontSize: 26, fontWeight: 700, letterSpacing: "-0.02em" }}>
              Findings AI Assistant
            </h1>
            <p style={{ margin: "6px 0 0", color: "var(--ink-2)", fontSize: 14, maxWidth: "72ch" }}>
              Ask anything about repository defects, root causes, security implications, or performance bottlenecks.
              Powered by RepoVue’s unified Gemini &amp; ML defect intelligence.
            </p>
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {analysisId ? (
              <Link
                to={`/analyses/${analysisId}/findings`}
                className="btn"
                style={{ textDecoration: "none", fontSize: 12.5 }}
              >
                Findings Table →
              </Link>
            ) : null}
            <button
              className="btn"
              onClick={handleClearHistory}
              style={{ fontSize: 12.5, color: "var(--ink-3)" }}
              title="Reset conversation transcript"
            >
              Reset Chat
            </button>
          </div>
        </div>

        {/* Status / Scope bar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            marginTop: 14,
            padding: "8px 14px",
            background: "var(--paper-2)",
            border: "1px solid var(--rule-2)",
            borderRadius: 6,
            fontSize: 12.5,
            flexWrap: "wrap",
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 500 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--pass)" }} />
            <span>Scope:</span>
          </span>
          <span className="mono" style={{ color: "var(--ink-2)" }}>
            {summaryApi.data?.repository?.full_name ?? (analysisId ? `Analysis ${analysisId.slice(0, 8)}` : "All Analyses")}
          </span>

          {summaryApi.data ? (
            <div style={{ display: "flex", gap: 8, marginLeft: "auto", flexWrap: "wrap" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--fail)" }}>
                {summaryApi.data.findings_by_severity.critical ?? 0} Critical
              </span>
              <span className="mono" style={{ fontSize: 11, color: "var(--warn)" }}>
                {summaryApi.data.findings_by_severity.high ?? 0} High
              </span>
              <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
                {Object.values(summaryApi.data.findings_by_severity).reduce((a, b) => a + b, 0)} Total Findings
              </span>
            </div>
          ) : null}
        </div>

        {/* Focused Finding Banner if query param is set */}
        {findingId && focusedFinding.data ? (
          <div
            style={{
              marginTop: 10,
              padding: "10px 14px",
              background: "var(--accent-soft)",
              border: "1px solid var(--accent)",
              borderRadius: 6,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
              <span style={{ fontSize: 16 }}>🎯</span>
              <span>
                <strong>Focused on Finding:</strong> {focusedFinding.data.title}
              </span>
              <SeverityBadge value={focusedFinding.data.severity} />
              <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
                {focusedFinding.data.path}:{focusedFinding.data.start_line}
              </span>
            </div>
            <button
              onClick={clearFocusedFinding}
              className="btn"
              style={{ fontSize: 11, padding: "4px 8px", background: "var(--paper)" }}
            >
              Clear Focus ✕
            </button>
          </div>
        ) : null}
      </header>

      {/* Main Chat Container */}
      <div
        style={{
          border: "1px solid var(--rule)",
          borderRadius: 8,
          background: "var(--paper)",
          boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
          display: "flex",
          flexDirection: "column",
          minHeight: 520,
        }}
      >
        {/* Messages Stream */}
        <div
          style={{
            flex: 1,
            padding: "24px 24px 16px",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 20,
          }}
        >
          {messages.map((m) => (
            <MessageRow key={m.id} message={m} onSelectQuestion={handleSend} />
          ))}

          {loading ? (
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start", maxWidth: "80%" }}>
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "50%",
                  background: "var(--accent-soft)",
                  color: "var(--accent)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 14,
                  flexShrink: 0,
                  fontWeight: 700,
                }}
              >
                AI
              </div>
              <div
                style={{
                  background: "var(--paper-2)",
                  border: "1px solid var(--rule-2)",
                  borderRadius: 8,
                  padding: "12px 18px",
                  fontSize: 13.5,
                  color: "var(--ink-2)",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <span className="loading-spinner" style={{ display: "inline-block", width: 14, height: 14, border: "2px solid var(--accent)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                <span>Reviewing findings evidence &amp; consulting model...</span>
              </div>
            </div>
          ) : null}

          {chatError ? (
            <div style={{ maxWidth: "85%", alignSelf: "flex-start" }}>
              <ErrorBox message={chatError} onRetry={() => handleSend(messages[messages.length - 1]?.content)} />
            </div>
          ) : null}

          <div ref={messagesEndRef} />
        </div>

        {/* Input & Quick Chips Footer */}
        <div
          style={{
            borderTop: "1px solid var(--rule)",
            padding: "16px 20px",
            background: "var(--paper-2)",
            borderRadius: "0 0 8px 8px",
          }}
        >
          {/* Recent Suggested Questions Pills */}
          {messages.length > 0 && messages[messages.length - 1]?.suggestedQuestions?.length ? (
            <div style={{ marginBottom: 12 }}>
              <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 6 }}>
                💡 Suggested follow-ups:
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {messages[messages.length - 1].suggestedQuestions!.map((q, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSend(q)}
                    disabled={loading}
                    style={{
                      background: "var(--paper)",
                      border: "1px solid var(--rule)",
                      borderRadius: 14,
                      padding: "4px 11px",
                      fontSize: 12,
                      color: "var(--ink)",
                      cursor: "pointer",
                      textAlign: "left",
                      transition: "all 0.15s ease",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                    onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--rule)")}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {/* Input Box */}
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
            <textarea
              ref={inputRef}
              rows={2}
              value={inputQuery}
              onChange={(e) => setInputQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything about findings, bugs, CVEs, architecture, or code fixes... (Press Enter to send)"
              style={{
                flex: 1,
                padding: "10px 14px",
                borderRadius: 6,
                border: "1px solid var(--rule)",
                background: "var(--paper)",
                color: "var(--ink)",
                fontSize: 13.5,
                lineHeight: 1.45,
                fontFamily: "inherit",
                resize: "vertical",
                minHeight: 46,
                maxHeight: 140,
                outline: "none",
              }}
            />
            <button
              className="btn-primary"
              onClick={() => handleSend()}
              disabled={loading || !inputQuery.trim()}
              style={{
                padding: "10px 20px",
                height: 46,
                fontWeight: 600,
                fontSize: 13.5,
                cursor: loading || !inputQuery.trim() ? "not-allowed" : "pointer",
                opacity: loading || !inputQuery.trim() ? 0.6 : 1,
                flexShrink: 0,
              }}
            >
              {loading ? "Thinking…" : "Send →"}
            </button>
          </div>
          <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 6, display: "flex", justifyContent: "space-between" }}>
            <span>Press Enter to send · Shift+Enter for new line</span>
            <span>Grounded in RepoVue Findings Database</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageRow({
  message,
  onSelectQuestion,
}: {
  message: MessageItem;
  onSelectQuestion: (q: string) => void;
}) {
  const isUser = message.role === "user";
  const navigate = useNavigate();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: isUser ? "row-reverse" : "row",
        gap: 12,
        alignItems: "flex-start",
        maxWidth: isUser ? "85%" : "92%",
        alignSelf: isUser ? "flex-end" : "flex-start",
      }}
    >
      {/* Avatar */}
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: "50%",
          background: isUser ? "var(--ink)" : "var(--accent-soft)",
          color: isUser ? "var(--paper)" : "var(--accent)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 12.5,
          fontWeight: 700,
          flexShrink: 0,
        }}
      >
        {isUser ? "You" : "AI"}
      </div>

      {/* Bubble */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Message Meta */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 4,
            justifyContent: isUser ? "flex-end" : "flex-start",
          }}
        >
          <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>
            {isUser ? "You" : "RepoVue Doctor"}
          </span>
          <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>
            {message.timestamp}
          </span>
          {message.provider ? (
            <span
              className="mono"
              style={{
                fontSize: 10,
                padding: "1px 6px",
                borderRadius: 3,
                background: "var(--rule-2)",
                color: "var(--ink-2)",
              }}
            >
              {message.provider}
            </span>
          ) : null}
        </div>

        {/* Text Content */}
        <div
          style={{
            background: isUser ? "var(--ink)" : "var(--paper-2)",
            color: isUser ? "var(--paper)" : "var(--ink)",
            border: isUser ? "none" : "1px solid var(--rule-2)",
            borderRadius: isUser ? "8px 2px 8px 8px" : "2px 8px 8px 8px",
            padding: "14px 18px",
            fontSize: 13.8,
            lineHeight: 1.6,
            wordBreak: "break-word",
          }}
        >
          {renderMarkdownContent(message.content, isUser)}
        </div>

        {/* Referenced Findings Cards */}
        {!isUser && message.referencedFindings && message.referencedFindings.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 6 }}>
              📌 Referenced findings in this analysis:
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 8 }}>
              {message.referencedFindings.map((ref) => (
                <div
                  key={ref.id}
                  onClick={() => navigate(`/findings/${ref.id}`)}
                  style={{
                    background: "var(--paper)",
                    border: "1px solid var(--rule)",
                    borderRadius: 5,
                    padding: "9px 12px",
                    cursor: "pointer",
                    transition: "border-color 0.15s ease",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--rule)")}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <SeverityBadge value={ref.severity} />
                      <span style={{ fontSize: 11, fontWeight: 600 }}>{categoryLabel(ref.category)}</span>
                    </div>
                    {ref.cwe ? (
                      <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                        {ref.cwe}
                      </span>
                    ) : null}
                  </div>
                  <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--ink)", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {ref.title}
                  </div>
                  <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", display: "flex", justifyContent: "space-between" }}>
                    <span>{ref.path}:{ref.start_line}</span>
                    <span style={{ color: "var(--accent)" }}>View →</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* Suggested Questions inside message bubble */}
        {!isUser && message.suggestedQuestions && message.suggestedQuestions.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            <div className="mono" style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 6 }}>
              💡 Follow-up questions:
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {message.suggestedQuestions.map((q, idx) => (
                <button
                  key={idx}
                  onClick={() => onSelectQuestion(q)}
                  style={{
                    background: "var(--paper)",
                    border: "1px solid var(--rule-2)",
                    borderRadius: 12,
                    padding: "3px 9px",
                    fontSize: 11.5,
                    color: "var(--ink)",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "border-color 0.15s ease",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--rule-2)")}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Lightweight, zero-dependency Markdown renderer supporting:
 * - Code blocks (```language ... ```)
 * - Headers (###, ##, #)
 * - Lists (- or * or 1.)
 * - Inline code (`code`)
 * - Bold (**text**)
 * - Italic (*text*)
 */
function renderMarkdownContent(content: string, isUser: boolean) {
  if (isUser) {
    return <div style={{ whiteSpace: "pre-wrap" }}>{content}</div>;
  }

  // Split by code blocks ```
  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {parts.map((part, index) => {
        if (part.startsWith("```") && part.endsWith("```")) {
          const lines = part.slice(3, -3).trim().split("\n");
          const firstLine = lines[0].trim();
          const language = /^[a-z0-9_-]+$/i.test(firstLine) ? firstLine : "";
          const codeBody = language ? lines.slice(1).join("\n") : lines.join("\n");

          return (
            <div
              key={index}
              style={{
                background: "var(--paper)",
                border: "1px solid var(--rule-2)",
                borderRadius: 5,
                overflow: "hidden",
                margin: "4px 0",
              }}
            >
              {language ? (
                <div
                  className="mono"
                  style={{
                    background: "var(--paper-2)",
                    padding: "3px 10px",
                    fontSize: 10.5,
                    color: "var(--ink-3)",
                    borderBottom: "1px solid var(--rule-2)",
                  }}
                >
                  {language}
                </div>
              ) : null}
              <pre
                className="mono"
                style={{
                  margin: 0,
                  padding: "10px 14px",
                  fontSize: 12,
                  overflowX: "auto",
                  color: "var(--ink)",
                  lineHeight: 1.5,
                }}
              >
                <code>{codeBody}</code>
              </pre>
            </div>
          );
        }

        // Render regular markdown text lines
        return (
          <div key={index} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {part.split("\n\n").map((paragraph, pIdx) => {
              const trimmed = paragraph.trim();
              if (!trimmed) return null;

              // Check for headings
              if (trimmed.startsWith("### ")) {
                return (
                  <h3 key={pIdx} style={{ margin: "6px 0 2px", fontSize: 15, fontWeight: 700, color: "var(--ink)" }}>
                    {renderInlineFormatted(trimmed.slice(4))}
                  </h3>
                );
              }
              if (trimmed.startsWith("## ")) {
                return (
                  <h2 key={pIdx} style={{ margin: "8px 0 2px", fontSize: 16.5, fontWeight: 700, color: "var(--ink)" }}>
                    {renderInlineFormatted(trimmed.slice(3))}
                  </h2>
                );
              }
              if (trimmed.startsWith("# ")) {
                return (
                  <h1 key={pIdx} style={{ margin: "10px 0 3px", fontSize: 18, fontWeight: 700, color: "var(--ink)" }}>
                    {renderInlineFormatted(trimmed.slice(2))}
                  </h1>
                );
              }

              // Check for list items
              const lines = paragraph.split("\n");
              if (lines.every((l) => l.trim().startsWith("- ") || l.trim().startsWith("* ") || /^\d+\.\s/.test(l.trim()))) {
                return (
                  <ul key={pIdx} style={{ margin: "2px 0", paddingLeft: 20 }}>
                    {lines.map((l, lIdx) => {
                      const itemText = l.trim().replace(/^[-*]\s+|\d+\.\s+/, "");
                      return (
                        <li key={lIdx} style={{ marginBottom: 4 }}>
                          {renderInlineFormatted(itemText)}
                        </li>
                      );
                    })}
                  </ul>
                );
              }

              return (
                <p key={pIdx} style={{ margin: 0 }}>
                  {renderInlineFormatted(paragraph)}
                </p>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function renderInlineFormatted(text: string) {
  // Regex to match inline code, bold, italics
  const regex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  const tokens = text.split(regex);

  return tokens.map((token, i) => {
    if (token.startsWith("`") && token.endsWith("`")) {
      return (
        <code
          key={i}
          className="mono"
          style={{
            background: "var(--rule-2)",
            padding: "2px 5px",
            borderRadius: 3,
            fontSize: 12,
            color: "var(--accent)",
          }}
        >
          {token.slice(1, -1)}
        </code>
      );
    }
    if (token.startsWith("**") && token.endsWith("**")) {
      return <strong key={i}>{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith("*") && token.endsWith("*")) {
      return <em key={i}>{token.slice(1, -1)}</em>;
    }
    return token;
  });
}
