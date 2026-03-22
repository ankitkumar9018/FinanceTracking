"use client";

import { useEffect, useState } from "react";
import { Toaster } from "react-hot-toast";

export function ToasterProvider() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <Toaster
      position="top-right"
      toastOptions={{
        className:
          "!bg-[hsl(var(--card))] !text-[hsl(var(--card-foreground))] !border !border-[hsl(var(--border))]",
      }}
    />
  );
}
