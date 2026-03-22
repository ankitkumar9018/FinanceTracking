"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles,
  Upload,
  LayoutDashboard,
  Bell,
  PartyPopper,
  ChevronRight,
  ChevronLeft,
  X,
  FileSpreadsheet,
  PenLine,
  Settings,
} from "lucide-react";
import Link from "next/link";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface OnboardingWizardProps {
  onComplete: () => void;
}

interface StepProps {
  onNext: () => void;
  onBack?: () => void;
  onSkip: () => void;
  isFirst: boolean;
  isLast: boolean;
}

const TOTAL_STEPS = 5;

/* ------------------------------------------------------------------ */
/*  Step 1: Welcome                                                    */
/* ------------------------------------------------------------------ */

function WelcomeStep({ onNext }: StepProps) {
  return (
    <div className="flex flex-col items-center text-center">
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 200, damping: 15, delay: 0.1 }}
        className="flex h-24 w-24 items-center justify-center rounded-2xl bg-[hsl(var(--primary))]/10"
      >
        <motion.div
          animate={{ rotate: [0, 10, -10, 0] }}
          transition={{ duration: 2, repeat: Infinity, repeatDelay: 1 }}
        >
          <Sparkles className="h-12 w-12 text-[hsl(var(--primary))]" />
        </motion.div>
      </motion.div>

      <motion.h2
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mt-8 text-2xl font-bold"
      >
        Welcome to FinanceTracker
      </motion.h2>

      <motion.p
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="mt-3 max-w-sm text-sm text-[hsl(var(--muted-foreground))]"
      >
        Your personal investment portfolio tracker for Indian and German markets.
        Let us show you around in just a few steps.
      </motion.p>

      <motion.button
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        onClick={onNext}
        className="mt-8 inline-flex items-center gap-2 rounded-lg bg-[hsl(var(--primary))] px-6 py-3 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
      >
        Get Started
        <ChevronRight className="h-4 w-4" />
      </motion.button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Step 2: Import                                                     */
/* ------------------------------------------------------------------ */

function ImportStep({ onNext, onBack }: StepProps) {
  return (
    <div className="flex flex-col items-center text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-[hsl(var(--primary))]/10">
        <Upload className="h-10 w-10 text-[hsl(var(--primary))]" />
      </div>

      <h2 className="mt-6 text-2xl font-bold">Import Your Portfolio</h2>
      <p className="mt-3 max-w-sm text-sm text-[hsl(var(--muted-foreground))]">
        Get started quickly by importing your existing holdings from an Excel file,
        or add them manually one by one.
      </p>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <Link
          href="/import"
          onClick={onNext}
          className="inline-flex items-center gap-2 rounded-lg bg-[hsl(var(--primary))] px-5 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
        >
          <FileSpreadsheet className="h-4 w-4" />
          Import from Excel
        </Link>
        <Link
          href="/holdings"
          onClick={onNext}
          className="inline-flex items-center gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-5 py-2.5 text-sm font-medium text-[hsl(var(--card-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
        >
          <PenLine className="h-4 w-4" />
          Add Manually
        </Link>
      </div>

      <div className="mt-6 flex gap-3">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
        >
          <ChevronLeft className="h-4 w-4" />
          Back
        </button>
        <button
          onClick={onNext}
          className="inline-flex items-center gap-1 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
        >
          Skip for now
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Step 3: Dashboard Color Codes                                      */
/* ------------------------------------------------------------------ */

function DashboardStep({ onNext, onBack }: StepProps) {
  const colorCodes = [
    { color: "bg-red-700", label: "Large loss (> 10%)" },
    { color: "bg-red-400", label: "Moderate loss (2-10%)" },
    { color: "bg-gray-400", label: "Neutral (-2% to 2%)" },
    { color: "bg-green-400", label: "Moderate gain (2-10%)" },
    { color: "bg-green-700", label: "Large gain (> 10%)" },
  ];

  return (
    <div className="flex flex-col items-center text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-[hsl(var(--primary))]/10">
        <LayoutDashboard className="h-10 w-10 text-[hsl(var(--primary))]" />
      </div>

      <h2 className="mt-6 text-2xl font-bold">Your Dashboard</h2>
      <p className="mt-3 max-w-sm text-sm text-[hsl(var(--muted-foreground))]">
        Your dashboard uses color coding to help you quickly assess performance
        at a glance. Here is what the colors mean:
      </p>

      <div className="mt-6 w-full max-w-xs space-y-2.5">
        {colorCodes.map((item) => (
          <div
            key={item.label}
            className="flex items-center gap-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-2.5"
          >
            <div className={`h-4 w-4 shrink-0 rounded ${item.color}`} />
            <span className="text-sm text-[hsl(var(--card-foreground))]">
              {item.label}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-6 flex gap-3">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
        >
          <ChevronLeft className="h-4 w-4" />
          Back
        </button>
        <button
          onClick={onNext}
          className="inline-flex items-center gap-2 rounded-lg bg-[hsl(var(--primary))] px-5 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Step 4: Alerts                                                     */
/* ------------------------------------------------------------------ */

function AlertsStep({ onNext, onBack }: StepProps) {
  return (
    <div className="flex flex-col items-center text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-[hsl(var(--primary))]/10">
        <Bell className="h-10 w-10 text-[hsl(var(--primary))]" />
      </div>

      <h2 className="mt-6 text-2xl font-bold">Stay Informed</h2>
      <p className="mt-3 max-w-sm text-sm text-[hsl(var(--muted-foreground))]">
        Set up alerts and notifications to stay on top of your investments.
        Configure price alerts, portfolio thresholds, and market updates
        delivered via email, push notifications, or in-app.
      </p>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <Link
          href="/settings"
          onClick={onNext}
          className="inline-flex items-center gap-2 rounded-lg bg-[hsl(var(--primary))] px-5 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
        >
          <Settings className="h-4 w-4" />
          Configure in Settings
        </Link>
      </div>

      <div className="mt-6 flex gap-3">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
        >
          <ChevronLeft className="h-4 w-4" />
          Back
        </button>
        <button
          onClick={onNext}
          className="inline-flex items-center gap-1 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
        >
          Skip for now
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Step 5: Done                                                       */
/* ------------------------------------------------------------------ */

function DoneStep({ onNext }: StepProps) {
  /* Confetti-like animated particles */
  const particles = Array.from({ length: 20 }, (_, i) => ({
    id: i,
    x: Math.random() * 300 - 150,
    y: -(Math.random() * 200 + 100),
    rotate: Math.random() * 360,
    scale: Math.random() * 0.5 + 0.5,
    color: [
      "bg-[hsl(var(--primary))]",
      "bg-green-500",
      "bg-yellow-500",
      "bg-pink-500",
      "bg-blue-500",
      "bg-purple-500",
    ][Math.floor(Math.random() * 6)],
  }));

  return (
    <div className="relative flex flex-col items-center text-center overflow-hidden">
      {/* Confetti particles */}
      {particles.map((p) => (
        <motion.div
          key={p.id}
          className={`absolute h-2 w-2 rounded-full ${p.color}`}
          initial={{ x: 0, y: 0, opacity: 1, scale: 0 }}
          animate={{
            x: p.x,
            y: p.y,
            opacity: [1, 1, 0],
            scale: p.scale,
            rotate: p.rotate,
          }}
          transition={{
            duration: 1.5,
            delay: Math.random() * 0.3,
            ease: "easeOut",
          }}
        />
      ))}

      <motion.div
        initial={{ scale: 0, rotate: -20 }}
        animate={{ scale: 1, rotate: 0 }}
        transition={{ type: "spring", stiffness: 200, damping: 12 }}
        className="flex h-24 w-24 items-center justify-center rounded-2xl bg-green-500/10"
      >
        <PartyPopper className="h-12 w-12 text-green-500" />
      </motion.div>

      <motion.h2
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mt-8 text-2xl font-bold"
      >
        You&apos;re All Set!
      </motion.h2>

      <motion.p
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="mt-3 max-w-sm text-sm text-[hsl(var(--muted-foreground))]"
      >
        Your FinanceTracker is ready to go. Start exploring your dashboard,
        import your portfolio, and let AI help you make informed decisions.
      </motion.p>

      <motion.button
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        onClick={onNext}
        className="mt-8 inline-flex items-center gap-2 rounded-lg bg-[hsl(var(--primary))] px-6 py-3 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors"
      >
        Go to Dashboard
        <ChevronRight className="h-4 w-4" />
      </motion.button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Step Dot Indicators                                                */
/* ------------------------------------------------------------------ */

function StepDots({
  current,
  total,
}: {
  current: number;
  total: number;
}) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: total }, (_, i) => (
        <button
          key={i}
          className={`h-2 rounded-full transition-all duration-300 ${
            i === current
              ? "w-6 bg-[hsl(var(--primary))]"
              : i < current
                ? "w-2 bg-[hsl(var(--primary))]/50"
                : "w-2 bg-[hsl(var(--muted))]"
          }`}
          aria-label={`Step ${i + 1}`}
        />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Wizard Component                                              */
/* ------------------------------------------------------------------ */

export function OnboardingWizard({ onComplete }: OnboardingWizardProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [direction, setDirection] = useState(1); // 1 = forward, -1 = backward

  const handleNext = useCallback(() => {
    if (currentStep === TOTAL_STEPS - 1) {
      onComplete();
      return;
    }
    setDirection(1);
    setCurrentStep((prev) => Math.min(prev + 1, TOTAL_STEPS - 1));
  }, [currentStep, onComplete]);

  const handleBack = useCallback(() => {
    setDirection(-1);
    setCurrentStep((prev) => Math.max(prev - 1, 0));
  }, []);

  const handleSkip = useCallback(() => {
    onComplete();
  }, [onComplete]);

  const stepProps: StepProps = {
    onNext: handleNext,
    onBack: handleBack,
    onSkip: handleSkip,
    isFirst: currentStep === 0,
    isLast: currentStep === TOTAL_STEPS - 1,
  };

  const steps = [
    <WelcomeStep key="welcome" {...stepProps} />,
    <ImportStep key="import" {...stepProps} />,
    <DashboardStep key="dashboard" {...stepProps} />,
    <AlertsStep key="alerts" {...stepProps} />,
    <DoneStep key="done" {...stepProps} />,
  ];

  const slideVariants = {
    enter: (dir: number) => ({
      x: dir > 0 ? 300 : -300,
      opacity: 0,
    }),
    center: {
      x: 0,
      opacity: 1,
    },
    exit: (dir: number) => ({
      x: dir > 0 ? -300 : 300,
      opacity: 0,
    }),
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 300, damping: 25 }}
        className="relative mx-4 w-full max-w-lg rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 shadow-2xl"
      >
        {/* Skip button (hidden on last step) */}
        {currentStep < TOTAL_STEPS - 1 && (
          <button
            onClick={handleSkip}
            className="absolute right-4 top-4 rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--accent-foreground))] transition-colors"
            title="Skip onboarding"
          >
            <X className="h-4 w-4" />
          </button>
        )}

        {/* Step Content with Slide Transitions */}
        <div className="relative min-h-90 overflow-hidden">
          <AnimatePresence mode="wait" custom={direction}>
            <motion.div
              key={currentStep}
              custom={direction}
              variants={slideVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.3, ease: "easeInOut" }}
              className="flex min-h-90 items-center justify-center"
            >
              {steps[currentStep]}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Step Dots */}
        <div className="mt-6 flex justify-center">
          <StepDots current={currentStep} total={TOTAL_STEPS} />
        </div>
      </motion.div>
    </motion.div>
  );
}
