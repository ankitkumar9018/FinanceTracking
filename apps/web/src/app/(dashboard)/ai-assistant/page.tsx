"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  AlertCircle,
  Bot,
  Send,
  Plus,
  MessageSquare,
  Loader2,
  Newspaper,
  WifiOff,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { api, ApiError } from "@/lib/api-client";
import { usePortfolioStore } from "@/stores/portfolio-store";
import { motion, AnimatePresence } from "framer-motion";
import { VoiceInput } from "@/components/ai/voice-input";
import InsightsPanel from "@/components/ai/insights-panel";
import DigestPanel from "@/components/ai/digest-panel";
import { Markdown } from "@/components/ai/markdown";
import toast from "react-hot-toast";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

/** Action the AI proposes to perform on the portfolio; requires an explicit
 * user Confirm before the backend executes it. */
interface ProposedAction {
  id: string | number;
  type: "add_transaction" | "add_holding" | "create_alert";
  summary: string;
  params: Record<string, unknown>;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  provider?: string;
  model?: string;
  timestamp: string;
  /** Client-side only: pending confirmation card attached to this reply. */
  proposedAction?: (ProposedAction & { sessionId: number }) | null;
}

interface ChatSession {
  id: number;
  message_count: number;
  created_at: string;
  last_message: string | null;
}

interface AIStatus {
  providers: Record<string, boolean>;
  active_provider: string | null;
  ai_available: boolean;
}

interface ChatResponse {
  response: string;
  provider: string;
  model: string;
  session_id: number;
  proposed_action?: ProposedAction | null;
}

const ACTION_TYPE_LABELS: Record<ProposedAction["type"], string> = {
  add_transaction: "Add transaction",
  add_holding: "Add holding",
  create_alert: "Create alert",
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function AIAssistantPage() {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [insightsOpen, setInsightsOpen] = useState(false);
  const [digestOpen, setDigestOpen] = useState(false);
  /** Last failed send, surfaced as a banner (NOT a fake assistant message). */
  const [sendError, setSendError] = useState<{ text: string; message: string } | null>(null);
  const [executingActionId, setExecutingActionId] = useState<ProposedAction["id"] | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Mirrors activeSessionId so async send callbacks can check, at resolve
  // time, whether the user has switched sessions since the request began.
  const activeSessionIdRef = useRef<number | null>(null);
  // Set before programmatically switching to a server-assigned session id so
  // the load effect below doesn't refetch and wipe the locally appended
  // messages (and any attached proposed-action card).
  const skipNextSessionLoadRef = useRef(false);

  /* ---- Scroll to bottom on new messages ---- */
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  /* ---- Load status and sessions on mount ---- */
  useEffect(() => {
    loadInitialData();
  }, []);

  async function loadInitialData() {
    setLoading(true);
    try {
      const [statusData, sessionsData] = await Promise.all([
        api.get<AIStatus>("/ai/status"),
        api.get<ChatSession[]>("/ai/sessions"),
      ]);
      setStatus(statusData);
      setSessions(sessionsData);
    } catch {
      /* empty */
    } finally {
      setLoading(false);
    }
  }

  /* ---- Load messages when session changes ---- */
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
    if (activeSessionId === null) return;
    // Skip the refetch when the switch came from a send that already appended
    // the messages locally (refetching would drop the proposed-action card).
    if (skipNextSessionLoadRef.current) {
      skipNextSessionLoadRef.current = false;
      return;
    }
    // Cancellation guard: switching sessions quickly must not let a slow earlier
    // response paint the previous session's messages over the current one.
    let cancelled = false;
    loadSessionMessages(activeSessionId, () => !cancelled);
    return () => {
      cancelled = true;
    };
  }, [activeSessionId]);

  async function loadSessionMessages(
    sessionId: number,
    isActive: () => boolean = () => true
  ) {
    try {
      const data = await api.get<{ messages: ChatMessage[] }>(`/ai/sessions/${sessionId}`);
      if (!isActive()) return;
      setMessages(data.messages || []);
    } catch {
      if (isActive()) setMessages([]);
    }
  }

  /* ---- Send message (shared by keyboard send, retry, and voice) ---- */
  async function sendMessage(text: string, { appendUser = true } = {}) {
    if (sending) return;
    // Capture the session at send time: a slow LLM reply must append into THIS
    // session only, and must not yank the user back if they switched away.
    const sessionAtSend = activeSessionId;
    setSendError(null);

    if (appendUser) {
      const userMessage: ChatMessage = {
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);
    }
    setSending(true);

    try {
      const result = await api.post<ChatResponse>("/ai/chat", {
        message: text,
        session_id: sessionAtSend,
      });

      // Session guard: if the user switched sessions (or started a new chat)
      // while waiting, drop the append/switch — the reply is persisted
      // server-side and will show up when they revisit that session.
      if (activeSessionIdRef.current !== sessionAtSend) return;

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: result.response,
        provider: result.provider,
        model: result.model,
        timestamp: new Date().toISOString(),
        proposedAction: result.proposed_action
          ? { ...result.proposed_action, sessionId: result.session_id }
          : undefined,
      };

      setMessages((prev) => [...prev, assistantMessage]);

      /* Update session id if this was a new session */
      if (sessionAtSend !== result.session_id) {
        skipNextSessionLoadRef.current = true;
        setActiveSessionId(result.session_id);
        /* Refresh sessions list */
        const sessionsData = await api.get<ChatSession[]>("/ai/sessions");
        setSessions(sessionsData);
      }
    } catch (err) {
      // Surface the real error OUTSIDE the transcript — but only if the user
      // is still on the session the send belonged to.
      if (activeSessionIdRef.current === sessionAtSend) {
        setSendError({
          text,
          message: err instanceof Error ? err.message : "Failed to get a response",
        });
      }
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || sending) return;
    setInput("");
    void sendMessage(trimmed);
  }

  /* ---- New chat ---- */
  function handleNewChat() {
    setActiveSessionId(null);
    setMessages([]);
    setInput("");
    setSendError(null);
    inputRef.current?.focus();
  }

  /* ---- Select session ---- */
  function handleSelectSession(session: ChatSession) {
    if (session.id !== activeSessionId) setSendError(null);
    setActiveSessionId(session.id);
  }

  /* ---- Handle voice transcript (guarded against parallel sends) ---- */
  function handleVoiceTranscript(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    /* Auto-submit the voice transcription through the shared send path */
    void sendMessage(trimmed);
  }

  /* ---- Proposed-action confirmation ---- */
  function removeActionCard(messageIndex: number) {
    setMessages((prev) =>
      prev.map((m, i) => (i === messageIndex ? { ...m, proposedAction: undefined } : m))
    );
  }

  async function handleExecuteAction(
    action: ProposedAction & { sessionId: number },
    messageIndex: number
  ) {
    if (executingActionId !== null) return;
    setExecutingActionId(action.id);
    try {
      const result = await api.post<{ detail?: string }>(
        `/ai/chat/actions/${action.id}/execute`,
        { session_id: action.sessionId }
      );
      toast.success(result?.detail || "Action executed");
      removeActionCard(messageIndex);
      // Refresh portfolio data so new transactions/holdings/alerts show up.
      const { activePortfolioId, fetchHoldings } = usePortfolioStore.getState();
      if (activePortfolioId != null) void fetchHoldings(activePortfolioId);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        toast.error("This action has expired — ask the assistant again.");
        removeActionCard(messageIndex);
      } else {
        toast.error(err instanceof Error ? err.message : "Failed to execute action");
      }
    } finally {
      setExecutingActionId(null);
    }
  }

  async function handleDismissAction(
    action: ProposedAction & { sessionId: number },
    messageIndex: number
  ) {
    removeActionCard(messageIndex);
    try {
      await api.post(`/ai/chat/actions/${action.id}/dismiss`, {
        session_id: action.sessionId,
      });
    } catch {
      /* Card is already gone locally; a 404 just means it had expired. */
    }
  }

  /* ---- Handle key press in textarea ---- */
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  /* ---- Format timestamp ---- */
  function formatTime(ts: string) {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatSessionDate(ts: string) {
    return new Date(ts).toLocaleDateString([], { month: "short", day: "numeric" });
  }

  /* ---- Provider status helpers ---- */
  const isOnline = status?.ai_available ?? false;
  const providerName = status?.active_provider ?? "Unknown";

  return (
    <div className="flex flex-col -m-6 h-[calc(100vh-8.5rem)]">
      {/* ---- Offline Banner ---- */}
      <AnimatePresence>
        {status && !isOnline && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--destructive))]/10 px-4 py-2 text-sm text-[hsl(var(--destructive))]"
          >
            <WifiOff className="h-4 w-4" />
            <span className="font-medium">AI Assistant Offline</span>
            <span className="text-[hsl(var(--muted-foreground))]">
              — No AI providers are currently available. Please check your configuration.
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex flex-1 overflow-hidden">
        {/* ---- Session Sidebar ---- */}
        <AnimatePresence initial={false}>
          {sidebarOpen && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 280, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex flex-col overflow-hidden border-r border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            >
              {/* Sidebar Header */}
              <div className="flex items-center justify-between border-b border-[hsl(var(--border))] p-3">
                <h2 className="text-sm font-semibold">Chat Sessions</h2>
                <button
                  onClick={handleNewChat}
                  className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
                  title="New Chat"
                  aria-label="Start new chat"
                >
                  <Plus className="h-4 w-4" />
                </button>
              </div>

              {/* Session List */}
              <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {loading ? (
                  <div className="space-y-2 p-2">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <div
                        key={i}
                        className="h-14 animate-pulse rounded-md bg-[hsl(var(--muted))]"
                      />
                    ))}
                  </div>
                ) : sessions.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-center">
                    <MessageSquare className="h-8 w-8 text-[hsl(var(--muted-foreground))]/30" />
                    <p className="mt-2 text-xs text-[hsl(var(--muted-foreground))]">
                      No conversations yet
                    </p>
                  </div>
                ) : (
                  sessions.map((session) => (
                    <button
                      key={session.id}
                      onClick={() => handleSelectSession(session)}
                      className={`w-full rounded-md p-2.5 text-left transition-colors ${
                        activeSessionId === session.id
                          ? "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
                          : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate text-sm font-medium">
                          {session.last_message
                            ? session.last_message.slice(0, 40) +
                              (session.last_message.length > 40 ? "..." : "")
                            : `Session #${session.id}`}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
                        <span>{formatSessionDate(session.created_at)}</span>
                        <span>{session.message_count} messages</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ---- Main Chat Area ---- */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Chat Header */}
          <div className="flex items-center gap-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              {sidebarOpen ? (
                <ChevronLeft className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
            <Bot className="h-5 w-5 text-[hsl(var(--primary))]" />
            <div className="flex-1">
              <h1 className="text-sm font-semibold">AI Assistant</h1>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                Ask questions about your portfolio, market trends, or financial advice
              </p>
            </div>
            {/* Status Indicator */}
            <div className="flex items-center gap-2">
              {status && (
                <div className="flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
                  <div
                    className={`h-2 w-2 rounded-full ${
                      isOnline ? "bg-green-500" : "bg-red-500"
                    }`}
                  />
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">
                    {isOnline ? providerName : "Offline"}
                  </span>
                </div>
              )}
              <button
                onClick={handleNewChat}
                className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                New Chat
              </button>
              <button
                onClick={() => {
                  setInsightsOpen((v) => !v);
                  setDigestOpen(false);
                }}
                aria-label={insightsOpen ? "Hide market insights" : "Show market insights"}
                aria-pressed={insightsOpen}
                title="Market Insights"
                className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                  insightsOpen
                    ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
                    : "border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
                }`}
              >
                <Sparkles className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Insights</span>
              </button>
              <button
                onClick={() => {
                  setDigestOpen((v) => !v);
                  setInsightsOpen(false);
                }}
                aria-label={digestOpen ? "Hide portfolio digest" : "Show portfolio digest"}
                aria-pressed={digestOpen}
                title="Portfolio Digest"
                className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                  digestOpen
                    ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]"
                    : "border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
                }`}
              >
                <Newspaper className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Digest</span>
              </button>
            </div>
          </div>

          {/* Messages Area */}
          <div className="flex flex-1 flex-col overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && !sending ? (
              <div className="flex flex-1 flex-col items-center justify-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[hsl(var(--primary))]/10">
                  <Bot className="h-8 w-8 text-[hsl(var(--primary))]" />
                </div>
                <h2 className="mt-4 text-lg font-semibold">How can I help you today?</h2>
                <p className="mt-1 max-w-md text-center text-sm text-[hsl(var(--muted-foreground))]">
                  Ask me about your portfolio performance, market analysis, risk assessment,
                  or any financial questions.
                </p>
                <div className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {[
                    "How is my portfolio performing?",
                    "What are the riskiest holdings?",
                    "Suggest rebalancing strategies",
                    "Analyze my dividend income",
                  ].map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => {
                        setInput(suggestion);
                        inputRef.current?.focus();
                      }}
                      className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3 text-left text-sm text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.map((msg, i) => (
                  <motion.div
                    key={`${msg.timestamp}-${msg.role}-${i}`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2 }}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[75%] rounded-lg px-4 py-3 ${
                        msg.role === "user"
                          ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                          : "border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
                      }`}
                    >
                      {msg.role === "assistant" && (
                        <div className="mb-1.5 flex items-center gap-2">
                          <Bot className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                          {msg.provider && (
                            <span className="rounded-full bg-[hsl(var(--primary))]/10 px-2 py-0.5 text-[10px] font-medium text-[hsl(var(--primary))]">
                              {msg.provider}
                              {msg.model ? ` / ${msg.model}` : ""}
                            </span>
                          )}
                        </div>
                      )}
                      {msg.role === "assistant" ? (
                        <Markdown content={msg.content} />
                      ) : (
                        <p className="whitespace-pre-wrap text-sm leading-relaxed">
                          {msg.content}
                        </p>
                      )}
                      {msg.role === "assistant" && msg.proposedAction && (
                        <div className="mt-3 rounded-md border border-[hsl(var(--primary))]/30 bg-[hsl(var(--primary))]/5 p-3">
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--primary))]">
                            <Zap className="h-3.5 w-3.5" />
                            Proposed action · {ACTION_TYPE_LABELS[msg.proposedAction.type] ?? msg.proposedAction.type}
                          </div>
                          <p className="mt-1.5 text-sm">{msg.proposedAction.summary}</p>
                          {Object.keys(msg.proposedAction.params || {}).length > 0 && (
                            <ul className="mt-2 space-y-0.5 text-xs text-[hsl(var(--muted-foreground))]">
                              {Object.entries(msg.proposedAction.params).map(([key, value]) => (
                                <li key={key} className="font-mono">
                                  <span className="font-semibold">{key}</span>:{" "}
                                  {typeof value === "object" && value !== null
                                    ? JSON.stringify(value)
                                    : String(value)}
                                </li>
                              ))}
                            </ul>
                          )}
                          <div className="mt-3 flex items-center gap-2">
                            <button
                              onClick={() => handleExecuteAction(msg.proposedAction!, i)}
                              disabled={executingActionId !== null}
                              className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
                            >
                              {executingActionId === msg.proposedAction.id && (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              )}
                              Confirm
                            </button>
                            <button
                              onClick={() => handleDismissAction(msg.proposedAction!, i)}
                              disabled={executingActionId !== null}
                              className="rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors disabled:opacity-50"
                            >
                              Dismiss
                            </button>
                          </div>
                        </div>
                      )}
                      <p
                        className={`mt-1.5 text-[10px] ${
                          msg.role === "user"
                            ? "text-[hsl(var(--primary-foreground))]/70"
                            : "text-[hsl(var(--muted-foreground))]"
                        }`}
                      >
                        {formatTime(msg.timestamp)}
                      </p>
                    </div>
                  </motion.div>
                ))}

                {/* Thinking indicator */}
                {sending && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex justify-start"
                  >
                    <div className="flex items-center gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
                      <Bot className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                      <div className="flex items-center gap-1">
                        <motion.span
                          animate={{ opacity: [0.3, 1, 0.3] }}
                          transition={{ duration: 1.2, repeat: Infinity, delay: 0 }}
                          className="h-2 w-2 rounded-full bg-[hsl(var(--primary))]"
                        />
                        <motion.span
                          animate={{ opacity: [0.3, 1, 0.3] }}
                          transition={{ duration: 1.2, repeat: Infinity, delay: 0.2 }}
                          className="h-2 w-2 rounded-full bg-[hsl(var(--primary))]"
                        />
                        <motion.span
                          animate={{ opacity: [0.3, 1, 0.3] }}
                          transition={{ duration: 1.2, repeat: Infinity, delay: 0.4 }}
                          className="h-2 w-2 rounded-full bg-[hsl(var(--primary))]"
                        />
                      </div>
                      <span className="text-xs text-[hsl(var(--muted-foreground))]">
                        Thinking...
                      </span>
                    </div>
                  </motion.div>
                )}
              </>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Send-error banner (outside the transcript) */}
          <AnimatePresence>
            {sendError && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="flex items-center gap-2 overflow-hidden border-t border-[hsl(var(--destructive))]/30 bg-[hsl(var(--destructive))]/10 px-4 py-2 text-sm"
              >
                <AlertCircle className="h-4 w-4 shrink-0 text-[hsl(var(--destructive))]" />
                <span className="flex-1 truncate text-[hsl(var(--destructive))]" title={sendError.message}>
                  {sendError.message}
                </span>
                <button
                  onClick={() => void sendMessage(sendError.text, { appendUser: false })}
                  disabled={sending}
                  className="rounded-md border border-[hsl(var(--destructive))]/40 px-2.5 py-1 text-xs font-medium text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive))]/10 transition-colors disabled:opacity-50"
                >
                  Retry
                </button>
                <button
                  onClick={() => setSendError(null)}
                  aria-label="Dismiss error"
                  className="rounded-md p-1 text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive))]/10 transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Input Area */}
          <div className="border-t border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  isOnline
                    ? "Ask a question about your finances..."
                    : "AI is currently offline..."
                }
                disabled={!isOnline || sending}
                rows={1}
                className="flex-1 resize-none rounded-lg border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] disabled:opacity-50"
                style={{ minHeight: "42px", maxHeight: "120px" }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = "auto";
                  target.style.height = Math.min(target.scrollHeight, 120) + "px";
                }}
              />
              <VoiceInput
                onTranscript={handleVoiceTranscript}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || sending || !isOnline}
                className="flex h-10.5 w-10.5 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
              >
                {sending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="mt-2 text-[10px] text-[hsl(var(--muted-foreground))]">
              Press Enter to send, Shift+Enter for new line
            </p>
          </div>
        </div>

        {/* ---- Insights Panel (right, collapsible) ---- */}
        <AnimatePresence initial={false}>
          {insightsOpen && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 360, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex flex-col overflow-hidden border-l border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            >
              <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-3 py-2">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--muted-foreground))]">
                  <Sparkles className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                  AI Insights
                </span>
                <button
                  onClick={() => setInsightsOpen(false)}
                  aria-label="Close insights panel"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="min-w-90 flex-1 overflow-hidden">
                <InsightsPanel />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ---- Digest Panel (right, collapsible) ---- */}
        <AnimatePresence initial={false}>
          {digestOpen && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 360, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex flex-col overflow-hidden border-l border-[hsl(var(--border))] bg-[hsl(var(--card))]"
            >
              <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-3 py-2">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--muted-foreground))]">
                  <Newspaper className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                  Portfolio Digest
                </span>
                <button
                  onClick={() => setDigestOpen(false)}
                  aria-label="Close digest panel"
                  className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="min-w-90 flex-1 overflow-hidden">
                <DigestPanel />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
