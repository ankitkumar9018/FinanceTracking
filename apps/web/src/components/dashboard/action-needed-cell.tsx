"use client";

import { motion } from "framer-motion";
import { AlertTriangle, Trophy } from "lucide-react";

const ZONE_CONFIG: Record<string, { bg: string; text: string; label: string; icon?: React.ComponentType<{ className?: string }> }> = {
  N: {
    bg: "bg-[hsl(var(--alert-neutral-bg))]",
    text: "text-[hsl(var(--alert-neutral-text))]",
    label: "N",
  },
  Y_LOWER_MID: {
    bg: "bg-[hsl(var(--alert-light-red-bg))]",
    text: "text-[hsl(var(--alert-light-red-text))]",
    label: "Y",
  },
  Y_UPPER_MID: {
    bg: "bg-[hsl(var(--alert-light-green-bg))]",
    text: "text-[hsl(var(--alert-light-green-text))]",
    label: "Y",
  },
  Y_DARK_RED: {
    bg: "bg-[hsl(var(--alert-dark-red-bg))]",
    text: "text-[hsl(var(--alert-dark-red-text))]",
    label: "Y",
    icon: AlertTriangle,
  },
  Y_DARK_GREEN: {
    bg: "bg-[hsl(var(--alert-dark-green-bg))]",
    text: "text-[hsl(var(--alert-dark-green-text))]",
    label: "Y",
    icon: Trophy,
  },
};

interface Props {
  action: string;
  onClick?: () => void;
}

export function ActionNeededCell({ action, onClick }: Props) {
  const config = ZONE_CONFIG[action] || ZONE_CONFIG.N;
  const shouldPulse = action !== "N";
  const Icon = config.icon;

  return (
    <motion.button
      onClick={onClick}
      animate={shouldPulse ? { scale: [1, 1.05, 1] } : {}}
      transition={shouldPulse ? { duration: 2, repeat: Infinity, ease: "easeInOut" } : {}}
      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold cursor-pointer transition-shadow hover:ring-2 hover:ring-[hsl(var(--ring))] ${config.bg} ${config.text}`}
      title={`Action: ${action} — Click to view price chart`}
    >
      {Icon && <Icon className="h-3 w-3" />}
      {config.label}
    </motion.button>
  );
}
