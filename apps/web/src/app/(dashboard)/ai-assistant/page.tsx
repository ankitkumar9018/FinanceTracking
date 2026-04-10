"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  Bot,
  Send,
  Plus,
  MessageSquare,
  Loader2,
  Wifi,
  WifiOff,
  ChevronLeft,
  ChevronRight,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { motion, AnimatePresence } from "framer-motion";
import { VoiceInput } from "@/components/ai/voice-input";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  provider?: string;
  model?: string;
  timestamp: string;
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
}

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

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
    if (activeSessionId !== null) {
      loadSessionMessages(activeSessionId);
    }
  }, [activeSessionId]);

  async function loadSessionMessages(sessionId: number) {
    try {
      const data = await api.get<{ messages: ChatMessage[] }>(`/ai/sessions/${sessionId}`);
      setMessages(data.messages || []);
    } catch {
      setMessages([]);
    }
  }

  /* ---- Send message ---- */
  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || sending) return;

    const userMessage: ChatMessage = {
      role: "user",
      content: trimmed,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setSending(true);

    try {
      const result = await api.post<ChatResponse>("/ai/chat", {
        message: trimmed,
        session_id: activeSessionId,
      });

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: result.response,
        provider: result.provider,
        model: result.model,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);

      /* Update session id if this was a new session */
      if (activeSessionId !== result.session_id) {
        setActiveSessionId(result.session_id);
        /* Refresh sessions list */
        const sessionsData = await api.get<ChatSession[]>("/ai/sessions");
        setSessions(sessionsData);
      }
    } catch {
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: "Sorry, I encountered an error processing your request. Please try again.",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  /* ---- New chat ---- */
  function handleNewChat() {
    setActiveSessionId(null);
    setMessages([]);
    setInput("");
    inputRef.current?.focus();
  }

  /* ---- Select session ---- */
  function handleSelectSession(session: ChatSession) {
    setActiveSessionId(session.id);
  }

  /* ---- Handle voice transcript ---- */
  function handleVoiceTranscript(text: string) {
    if (!text.trim()) return;
    setInput(text);
    /* Auto-submit the voice transcription */
    const userMessage: ChatMessage = {
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setSending(true);

    api
      .post<ChatResponse>("/ai/chat", {
        message: text,
        session_id: activeSessionId,
      })
      .then(async (result) => {
        const assistantMessage: ChatMessage = {
          role: "assistant",
          content: result.response,
          provider: result.provider,
          model: result.model,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
        if (activeSessionId !== result.session_id) {
          setActiveSessionId(result.session_id);
          const sessionsData = await api.get<ChatSession[]>("/ai/sessions");
          setSessions(sessionsData);
        }
      })
      .catch(() => {
        const errorMessage: ChatMessage = {
          role: "assistant",
          content:
            "Sorry, I encountered an error processing your request. Please try again.",
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errorMessage]);
      })
      .finally(() => {
        setSending(false);
        setInput("");
        inputRef.current?.focus();
      });
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
                    key={i}
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
                      <p className="whitespace-pre-wrap text-sm leading-relaxed">
                        {msg.content}
                      </p>
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
      </div>
    </div>
  );
}
