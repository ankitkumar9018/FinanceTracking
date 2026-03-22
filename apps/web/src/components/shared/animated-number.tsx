"use client";

import { useEffect, useRef, useState } from "react";

interface AnimatedNumberProps {
  value: number;
  duration?: number;
  formatFn?: (n: number) => string;
  className?: string;
}

export function AnimatedNumber({
  value,
  duration = 800,
  formatFn = (n) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  className,
}: AnimatedNumberProps) {
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);
  const frameRef = useRef<number>(0);
  const currentRef = useRef(value);

  useEffect(() => {
    const from = prevRef.current;
    const to = value;
    const diff = to - from;

    if (Math.abs(diff) < 0.01) {
      setDisplay(to);
      prevRef.current = to;
      currentRef.current = to;
      return;
    }

    const start = performance.now();
    function animate(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = from + diff * eased;
      currentRef.current = current;
      setDisplay(current);

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(animate);
      } else {
        prevRef.current = to;
      }
    }

    frameRef.current = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(frameRef.current);
      prevRef.current = currentRef.current;
    };
  }, [value, duration]);

  const isPositive = value > (prevRef.current ?? 0);
  const isNegative = value < (prevRef.current ?? 0);

  return (
    <span
      className={`tabular-nums transition-colors duration-300 ${
        isPositive ? "text-[hsl(var(--profit))]" : isNegative ? "text-[hsl(var(--loss))]" : ""
      } ${className || ""}`}
    >
      {formatFn(display)}
    </span>
  );
}
