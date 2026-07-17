"use client";

import { useState } from "react";
import Link from "next/link";
import toast from "react-hot-toast";
import { api } from "@/lib/api-client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/auth/forgot-password", { email });
    } catch {
      // Intentionally ignore errors: the response is always generic so we
      // never reveal whether an account exists for this email.
    } finally {
      setLoading(false);
      setSubmitted(true);
      toast.success("If that email exists, a reset link was sent.");
    }
  }

  return (
    <>
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight">Forgot Password</h1>
        <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
          Enter your email and we&apos;ll send you a reset link
        </p>
      </div>

      {submitted ? (
        <div className="space-y-4">
          <p className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 px-4 py-3 text-sm text-[hsl(var(--muted-foreground))]">
            If that email exists, a reset link was sent. Check your inbox and
            follow the link to choose a new password.
          </p>
          <Link
            href="/login"
            className="block w-full h-10 rounded-md bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-sm font-medium hover:bg-[hsl(var(--primary))]/90 transition-colors text-center leading-10"
          >
            Back to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="flex h-10 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
              placeholder="you@example.com"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full h-10 rounded-md bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-sm font-medium hover:bg-[hsl(var(--primary))]/90 disabled:opacity-50 transition-colors"
          >
            {loading ? "Sending..." : "Send reset link"}
          </button>
        </form>
      )}

      <p className="text-center text-sm text-[hsl(var(--muted-foreground))]">
        Remember your password?{" "}
        <Link href="/login" className="text-[hsl(var(--primary))] hover:underline">
          Sign in
        </Link>
      </p>
    </>
  );
}
