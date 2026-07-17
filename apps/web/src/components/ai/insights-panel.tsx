"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  Newspaper,
  LineChart as LineChartIcon,
  Loader2,
  Search,
  Inbox,
  ExternalLink,
} from "lucide-react";
import toast from "react-hot-toast";
import { api } from "@/lib/api-client";
import { formatCurrency, currencyForExchange } from "@/lib/utils";

/* Recharts is heavy — load the prediction mini-chart lazily, client only */
const PredictionChart = dynamic(() => import("./prediction-chart"), {
  ssr: false,
  loading: () => (
    <div className="h-full w-full animate-pulse rounded-lg bg-[hsl(var(--muted))]/50" />
  ),
});

/* ------------------------------------------------------------------ */
/*  Types (mirror the backend AI/ML contracts)                        */
/* ------------------------------------------------------------------ */

interface PredictionPoint {
  date: string;
  predicted_price: number;
  confidence: number;
}

interface PredictionResult {
  symbol: string;
  current_price: number;
  predictions: PredictionPoint[];
  model_accuracy: number;
  direction: "up" | "down" | "neutral";
  confidence: number;
}

interface Anomaly {
  anomaly_type: string;
  severity: string;
  description: string;
  price: number;
  volume: number;
  score: number;
}

interface AnomalyResult {
  symbol: string;
  exchange: string;
  anomalies: Anomaly[];
  total_analyzed: number;
  anomaly_rate: number;
}

interface NewsItem {
  title: string;
  source: string;
  date: string;
  sentiment: string;
  score: number;
  url: string;
}

interface SentimentResult {
  symbol: string;
  overall_sentiment: "bullish" | "bearish" | "neutral";
  sentiment_score: number;
  news_items: NewsItem[];
  analysis_method: string;
}

/** Independent async state for each sub-panel. */
interface PanelState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

const idle = <T,>(): PanelState<T> => ({ data: null, loading: false, error: null });

type TabKey = "prediction" | "anomalies" | "sentiment";

const TABS: { key: TabKey; label: string; icon: typeof LineChartIcon }[] = [
  { key: "prediction", label: "Prediction", icon: LineChartIcon },
  { key: "anomalies", label: "Anomalies", icon: AlertTriangle },
  { key: "sentiment", label: "Sentiment", icon: Newspaper },
];

/* ------------------------------------------------------------------ */
/*  Small presentational helpers                                       */
/* ------------------------------------------------------------------ */

function directionStyles(direction: string) {
  switch (direction) {
    case "up":
    case "bullish":
      return { color: "#22c55e", cls: "bg-green-500/10 text-green-500", Icon: TrendingUp };
    case "down":
    case "bearish":
      return { color: "#ef4444", cls: "bg-red-500/10 text-red-500", Icon: TrendingDown };
    default:
      return {
        color: "hsl(var(--primary))",
        cls: "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]",
        Icon: Minus,
      };
  }
}

function severityCls(severity: string) {
  switch ((severity || "").toLowerCase()) {
    case "high":
    case "critical":
      return "bg-red-500/10 text-red-500 border-red-500/20";
    case "medium":
    case "moderate":
      return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    default:
      return "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] border-[hsl(var(--border))]";
  }
}

function PanelLoading({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <Loader2 className="h-6 w-6 animate-spin text-[hsl(var(--primary))]" />
      <p className="text-xs text-[hsl(var(--muted-foreground))]">{label}</p>
      <p className="text-[10px] text-[hsl(var(--muted-foreground))]/70">
        ML models can take a few seconds…
      </p>
    </div>
  );
}

function PanelEmpty({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <Inbox className="h-7 w-7 text-[hsl(var(--muted-foreground))]/40" />
      <p className="max-w-[220px] text-xs text-[hsl(var(--muted-foreground))]">{message}</p>
    </div>
  );
}

function PanelError({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <AlertTriangle className="h-7 w-7 text-[hsl(var(--destructive))]/70" />
      <p className="max-w-[220px] text-xs text-[hsl(var(--destructive))]">{message}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                           */
/* ------------------------------------------------------------------ */

export default function InsightsPanel() {
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("NSE");
  const [activeTab, setActiveTab] = useState<TabKey>("prediction");
  const [analyzed, setAnalyzed] = useState<string | null>(null);

  const [prediction, setPrediction] = useState<PanelState<PredictionResult>>(idle);
  const [anomalies, setAnomalies] = useState<PanelState<AnomalyResult>>(idle);
  const [sentiment, setSentiment] = useState<PanelState<SentimentResult>>(idle);

  const currency = currencyForExchange(exchange);

  /* Each panel fetches independently; one slow/failing model never blocks the
     others and never crashes the page. */
  async function loadPrediction(sym: string) {
    setPrediction({ data: null, loading: true, error: null });
    try {
      const data = await api.get<PredictionResult>(
        `/ai/prediction/${encodeURIComponent(sym)}?exchange=${encodeURIComponent(exchange)}&days_ahead=5`,
      );
      setPrediction({ data, loading: false, error: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load prediction";
      setPrediction({ data: null, loading: false, error: msg });
      toast.error(`Prediction: ${msg}`);
    }
  }

  async function loadAnomalies(sym: string) {
    setAnomalies({ data: null, loading: true, error: null });
    try {
      const data = await api.get<AnomalyResult>(
        `/ai/anomalies/${encodeURIComponent(sym)}?exchange=${encodeURIComponent(exchange)}&days=90`,
      );
      setAnomalies({ data, loading: false, error: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load anomalies";
      setAnomalies({ data: null, loading: false, error: msg });
      toast.error(`Anomalies: ${msg}`);
    }
  }

  async function loadSentiment(sym: string) {
    setSentiment({ data: null, loading: true, error: null });
    try {
      const data = await api.get<SentimentResult>(`/ai/sentiment/${encodeURIComponent(sym)}`);
      setSentiment({ data, loading: false, error: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load sentiment";
      setSentiment({ data: null, loading: false, error: msg });
      toast.error(`Sentiment: ${msg}`);
    }
  }

  function handleAnalyze(e?: React.FormEvent) {
    e?.preventDefault();
    const sym = symbol.trim().toUpperCase();
    if (!sym) {
      toast.error("Enter a stock symbol first");
      return;
    }
    setSymbol(sym);
    setAnalyzed(sym);
    /* Fire all three in parallel — independent loading states. */
    void loadPrediction(sym);
    void loadAnomalies(sym);
    void loadSentiment(sym);
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header: title + symbol/exchange controls */}
      <div className="border-b border-[hsl(var(--border))] p-3">
        <div className="mb-3 flex items-center gap-2">
          <LineChartIcon className="h-4 w-4 text-[hsl(var(--primary))]" />
          <h2 className="text-sm font-semibold">Market Insights</h2>
        </div>
        <form onSubmit={handleAnalyze} className="space-y-2">
          <div className="flex items-center gap-2">
            <input
              value={symbol}
              onChange={(ev) => setSymbol(ev.target.value)}
              placeholder="Symbol (e.g. RELIANCE)"
              aria-label="Stock symbol"
              className="h-9 flex-1 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm uppercase focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
            <select
              value={exchange}
              onChange={(ev) => setExchange(ev.target.value)}
              aria-label="Exchange"
              className="h-9 w-24 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            >
              <option value="NSE">NSE</option>
              <option value="BSE">BSE</option>
              <option value="XETRA">XETRA</option>
            </select>
          </div>
          <button
            type="submit"
            className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-3 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
          >
            <Search className="h-4 w-4" />
            Analyze
          </button>
        </form>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[hsl(var(--border))]">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              aria-label={`Show ${tab.label}`}
              aria-selected={active}
              role="tab"
              className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 px-2 py-2.5 text-xs font-medium transition-colors ${
                active
                  ? "border-[hsl(var(--primary))] text-[hsl(var(--primary))]"
                  : "border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Panel body */}
      <div className="flex-1 overflow-y-auto p-3">
        {!analyzed ? (
          <PanelEmpty message="Enter a symbol and press Analyze to see AI-powered prediction, anomaly and sentiment insights." />
        ) : (
          <>
            {activeTab === "prediction" && (
              <PredictionPanel
                state={prediction}
                currency={currency}
                onRetry={() => analyzed && loadPrediction(analyzed)}
              />
            )}
            {activeTab === "anomalies" && (
              <AnomaliesPanel state={anomalies} currency={currency} />
            )}
            {activeTab === "sentiment" && <SentimentPanel state={sentiment} />}
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Prediction sub-panel                                               */
/* ------------------------------------------------------------------ */

function PredictionPanel({
  state,
  currency,
  onRetry,
}: {
  state: PanelState<PredictionResult>;
  currency: string;
  onRetry: () => void;
}) {
  if (state.loading) return <PanelLoading label="Forecasting prices" />;
  if (state.error) return <PanelError message={state.error} />;
  if (!state.data) return <PanelEmpty message="No prediction available." />;

  const p = state.data;
  const { color, cls, Icon } = directionStyles(p.direction);
  const hasPredictions = p.predictions.length > 0;

  const chartData = [
    { label: "Now", price: p.current_price },
    ...p.predictions.map((pt) => ({
      label: shortDate(pt.date),
      price: pt.predicted_price,
    })),
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
            Current price
          </p>
          <p className="font-mono text-lg font-semibold">
            {formatCurrency(p.current_price, currency)}
          </p>
        </div>
        <div className="text-right">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${cls}`}
          >
            <Icon className="h-3.5 w-3.5" />
            {p.direction}
          </span>
          <p className="mt-1 text-[10px] text-[hsl(var(--muted-foreground))]">
            {(p.confidence * 100).toFixed(0)}% confidence
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between text-[10px] text-[hsl(var(--muted-foreground))]">
        <span>Model accuracy: {(p.model_accuracy * 100).toFixed(0)}%</span>
        <button
          onClick={onRetry}
          className="rounded px-1.5 py-0.5 hover:text-[hsl(var(--foreground))] hover:underline"
        >
          Refresh
        </button>
      </div>

      {hasPredictions ? (
        <>
          <div className="h-40 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-2">
            <PredictionChart data={chartData} currentPrice={p.current_price} color={color} />
          </div>
          <div className="overflow-hidden rounded-lg border border-[hsl(var(--border))]">
            <table className="w-full text-xs">
              <thead className="bg-[hsl(var(--muted))]/40 text-[hsl(var(--muted-foreground))]">
                <tr>
                  <th className="px-2.5 py-1.5 text-left font-medium">Date</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">Predicted</th>
                  <th className="px-2.5 py-1.5 text-right font-medium">Conf.</th>
                </tr>
              </thead>
              <tbody>
                {p.predictions.map((pt, i) => (
                  <tr key={i} className="border-t border-[hsl(var(--border))]">
                    <td className="px-2.5 py-1.5">{shortDate(pt.date)}</td>
                    <td className="px-2.5 py-1.5 text-right font-mono">
                      {formatCurrency(pt.predicted_price, currency)}
                    </td>
                    <td className="px-2.5 py-1.5 text-right text-[hsl(var(--muted-foreground))]">
                      {(pt.confidence * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <PanelEmpty message="Not enough historical data to generate a forecast for this symbol yet. Try again later." />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Anomalies sub-panel                                                */
/* ------------------------------------------------------------------ */

function AnomaliesPanel({
  state,
  currency,
}: {
  state: PanelState<AnomalyResult>;
  currency: string;
}) {
  if (state.loading) return <PanelLoading label="Scanning for anomalies" />;
  if (state.error) return <PanelError message={state.error} />;
  if (!state.data) return <PanelEmpty message="No anomaly data available." />;

  const a = state.data;
  if (a.anomalies.length === 0) {
    return (
      <PanelEmpty
        message={`No unusual activity detected across ${a.total_analyzed} analysed data points.`}
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[10px] text-[hsl(var(--muted-foreground))]">
        <span>{a.total_analyzed} points analysed</span>
        <span>{(a.anomaly_rate * 100).toFixed(1)}% anomaly rate</span>
      </div>
      <div className="space-y-2">
        {a.anomalies.map((an, i) => (
          <div
            key={i}
            className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3"
          >
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-sm font-medium capitalize">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                {an.anomaly_type.replace(/_/g, " ")}
              </span>
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${severityCls(an.severity)}`}
              >
                {an.severity}
              </span>
            </div>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">{an.description}</p>
            <div className="mt-2 flex items-center gap-3 text-[10px] text-[hsl(var(--muted-foreground))]">
              <span className="font-mono">{formatCurrency(an.price, currency)}</span>
              <span>Vol: {Intl.NumberFormat("en-IN", { notation: "compact" }).format(an.volume)}</span>
              <span>Score: {an.score.toFixed(2)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sentiment sub-panel                                                */
/* ------------------------------------------------------------------ */

function SentimentPanel({ state }: { state: PanelState<SentimentResult> }) {
  if (state.loading) return <PanelLoading label="Analysing news sentiment" />;
  if (state.error) return <PanelError message={state.error} />;
  if (!state.data) return <PanelEmpty message="No sentiment data available." />;

  const s = state.data;
  const { cls, Icon } = directionStyles(s.overall_sentiment);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
            Overall sentiment
          </p>
          <span
            className={`mt-1 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${cls}`}
          >
            <Icon className="h-3.5 w-3.5" />
            {s.overall_sentiment}
          </span>
        </div>
        <div className="text-right">
          <p className="text-[10px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
            Score
          </p>
          <p className="font-mono text-lg font-semibold">{s.sentiment_score.toFixed(2)}</p>
          <p className="text-[10px] text-[hsl(var(--muted-foreground))]">
            {s.analysis_method}
          </p>
        </div>
      </div>

      {s.news_items.length === 0 ? (
        <PanelEmpty message="No recent news found for this symbol." />
      ) : (
        <div className="space-y-2">
          {s.news_items.map((item, i) => {
            const tone = directionStyles(item.sentiment);
            const content = (
              <>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs font-medium leading-snug">{item.title}</p>
                  {item.url && (
                    <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-[hsl(var(--muted-foreground))]" />
                  )}
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-[10px] text-[hsl(var(--muted-foreground))]">
                  <span>{item.source}</span>
                  {item.date && <span>{shortDate(item.date)}</span>}
                  <span className={`ml-auto rounded-full px-1.5 py-0.5 font-semibold capitalize ${tone.cls}`}>
                    {item.sentiment} {item.score.toFixed(2)}
                  </span>
                </div>
              </>
            );
            return item.url ? (
              <a
                key={i}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 transition-colors hover:bg-[hsl(var(--accent))]"
              >
                {content}
              </a>
            ) : (
              <div
                key={i}
                className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3"
              >
                {content}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Utils                                                              */
/* ------------------------------------------------------------------ */

function shortDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
