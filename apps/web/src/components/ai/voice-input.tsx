"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, MicOff, Loader2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface VoiceInputProps {
  onTranscript: (text: string) => void;
  className?: string;
}

type VoiceState = "idle" | "recording" | "processing";

/* ------------------------------------------------------------------ */
/*  SpeechRecognition type shim (browser-native API)                   */
/* ------------------------------------------------------------------ */

interface SpeechRecognitionEvent {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionErrorEvent {
  error: string;
}

interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onspeechend: (() => void) | null;
}

declare global {
  interface Window {
    webkitSpeechRecognition: new () => SpeechRecognitionInstance;
    SpeechRecognition: new () => SpeechRecognitionInstance;
  }
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function isSpeechRecognitionSupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    "webkitSpeechRecognition" in window || "SpeechRecognition" in window
  );
}

function createRecognition(): SpeechRecognitionInstance | null {
  if (typeof window === "undefined") return null;
  const SpeechRecognitionCtor =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognitionCtor) return null;
  return new SpeechRecognitionCtor();
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function VoiceInput({ onTranscript, className = "" }: VoiceInputProps) {
  const [state, setState] = useState<VoiceState>("idle");
  const [supported, setSupported] = useState(true);
  const [interimText, setInterimText] = useState("");
  const [showTooltip, setShowTooltip] = useState(false);

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tooltipTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* ---- Check support on mount ---- */
  useEffect(() => {
    setSupported(isSpeechRecognitionSupported());
  }, []);

  /* ---- Cleanup on unmount ---- */
  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
      }
      if (tooltipTimerRef.current) {
        clearTimeout(tooltipTimerRef.current);
      }
    };
  }, []);

  /* ---- Reset silence timer ---- */
  const resetSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
    }
    silenceTimerRef.current = setTimeout(() => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    }, 3000);
  }, []);

  /* ---- Start recording ---- */
  const startRecording = useCallback(() => {
    const recognition = createRecognition();
    if (!recognition) return;

    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = "";
      let final = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          final += transcript;
        } else {
          interim += transcript;
        }
      }

      if (interim) {
        setInterimText(interim);
        resetSilenceTimer();
      }

      if (final) {
        setState("processing");
        setInterimText("");
        if (silenceTimerRef.current) {
          clearTimeout(silenceTimerRef.current);
        }
        onTranscript(final.trim());
        setState("idle");
      }
    };

    recognition.onerror = () => {
      setState("idle");
      setInterimText("");
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
      }
    };

    recognition.onend = () => {
      setState("idle");
      setInterimText("");
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
    setState("recording");
    resetSilenceTimer();
  }, [onTranscript, resetSilenceTimer]);

  /* ---- Stop recording ---- */
  const stopRecording = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
    }
    setState("idle");
    setInterimText("");
  }, []);

  /* ---- Toggle ---- */
  const handleToggle = useCallback(() => {
    if (!supported) {
      setShowTooltip(true);
      tooltipTimerRef.current = setTimeout(() => setShowTooltip(false), 2500);
      return;
    }
    if (state === "recording") {
      stopRecording();
    } else if (state === "idle") {
      startRecording();
    }
  }, [supported, state, startRecording, stopRecording]);

  /* ---- Waveform bars animation ---- */
  const waveformBars = [0, 1, 2, 3];

  return (
    <div className={`relative ${className}`}>
      {/* Interim text bubble */}
      <AnimatePresence>
        {interimText && state === "recording" && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="absolute bottom-full left-1/2 mb-2 -translate-x-1/2 whitespace-nowrap rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--popover))] px-3 py-1.5 text-xs text-[hsl(var(--popover-foreground))] shadow-lg"
          >
            {interimText}
            <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-[hsl(var(--popover))]" />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Unsupported tooltip */}
      <AnimatePresence>
        {showTooltip && !supported && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="absolute bottom-full left-1/2 mb-2 -translate-x-1/2 whitespace-nowrap rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--popover))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] shadow-lg"
          >
            Voice not supported in this browser
            <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-[hsl(var(--popover))]" />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Button */}
      <button
        type="button"
        onClick={handleToggle}
        className={`relative flex h-10.5 w-10.5 shrink-0 items-center justify-center rounded-lg transition-colors ${
          state === "recording"
            ? "bg-red-500/20 text-red-500 hover:bg-red-500/30"
            : state === "processing"
              ? "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]"
              : "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))]"
        } ${!supported ? "opacity-50 cursor-not-allowed" : ""}`}
        title={
          !supported
            ? "Voice not supported in this browser"
            : state === "recording"
              ? "Stop recording"
              : "Start voice input"
        }
      >
        {/* Pulsing ring when recording */}
        {state === "recording" && (
          <motion.span
            className="absolute inset-0 rounded-lg border-2 border-red-500"
            animate={{ scale: [1, 1.15, 1], opacity: [0.7, 0, 0.7] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          />
        )}

        {state === "processing" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : state === "recording" ? (
          <div className="flex items-center gap-0.75">
            {waveformBars.map((i) => (
              <motion.div
                key={i}
                className="w-0.75 rounded-full bg-red-500"
                animate={{
                  height: ["8px", "16px", "8px"],
                }}
                transition={{
                  duration: 0.6,
                  repeat: Infinity,
                  ease: "easeInOut",
                  delay: i * 0.15,
                }}
              />
            ))}
          </div>
        ) : supported ? (
          <Mic className="h-4 w-4" />
        ) : (
          <MicOff className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}
