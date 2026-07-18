"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import {
  Copy,
  Download,
  KeyRound,
  Loader2,
  Lock,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
} from "lucide-react";
import toast from "react-hot-toast";

interface MeResponse {
  id: number;
  email: string;
  totp_enabled?: boolean;
}

interface TwoFactorSetupResponse {
  totp_secret: string;
  totp_uri: string;
}

interface TwoFactorVerifyResponse {
  verified: boolean;
  message: string;
  backup_codes: string[];
}

interface BackupCodesResponse {
  backup_codes: string[];
  message?: string;
}

interface BackupCodesStatusResponse {
  remaining: number;
}

const inputClass =
  "h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]";

async function copyToClipboard(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${label} copied to clipboard`);
  } catch {
    toast.error("Failed to copy to clipboard");
  }
}

function downloadBackupCodes(codes: string[]) {
  const contents =
    "FinanceTracker 2FA backup codes\n" +
    "Each code works once. Store them somewhere safe.\n\n" +
    codes.join("\n") +
    "\n";
  const blob = new Blob([contents], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "financetracker-backup-codes.txt";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function SecuritySection() {
  /* ---- 2FA state ---- */
  const [totpEnabled, setTotpEnabled] = useState<boolean | null>(null);
  const [setup, setSetup] = useState<TwoFactorSetupResponse | null>(null);
  const [setupLoading, setSetupLoading] = useState(false);
  const [verifyCode, setVerifyCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [disableCode, setDisableCode] = useState("");
  const [disabling, setDisabling] = useState(false);

  /* ---- Backup codes state ---- */
  // Raw codes are shown exactly once (right after enabling or regenerating).
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [backupRemaining, setBackupRemaining] = useState<number | null>(null);
  const [showRegen, setShowRegen] = useState(false);
  const [regenCode, setRegenCode] = useState("");
  const [regenerating, setRegenerating] = useState(false);

  /* ---- Change password state ---- */
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  async function refreshBackupStatus() {
    try {
      const res = await api.get<BackupCodesStatusResponse>(
        "/auth/2fa/backup-codes/status",
      );
      setBackupRemaining(res.remaining);
    } catch {
      setBackupRemaining(null);
    }
  }

  useEffect(() => {
    api
      .get<MeResponse>("/auth/me")
      .then((me) => {
        const enabled = !!me.totp_enabled;
        setTotpEnabled(enabled);
        if (enabled) void refreshBackupStatus();
      })
      .catch(() => setTotpEnabled(false));
  }, []);

  /* ---- 2FA handlers ---- */
  async function startSetup() {
    setSetupLoading(true);
    try {
      const res = await api.post<TwoFactorSetupResponse>("/auth/2fa/setup");
      setSetup(res);
      setVerifyCode("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start 2FA setup");
    } finally {
      setSetupLoading(false);
    }
  }

  async function handleVerify() {
    if (!setup || verifyCode.length !== 6) return;
    setVerifying(true);
    try {
      const res = await api.post<TwoFactorVerifyResponse>("/auth/2fa/verify", {
        secret: setup.totp_secret,
        code: verifyCode,
      });
      toast.success("Two-factor authentication is now active");
      setTotpEnabled(true);
      setSetup(null);
      setVerifyCode("");
      // Surface the one-time backup codes right away.
      setBackupCodes(res.backup_codes ?? null);
      setBackupRemaining(res.backup_codes?.length ?? 0);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Invalid TOTP code");
    } finally {
      setVerifying(false);
    }
  }

  async function handleDisable() {
    if (disableCode.length !== 6) return;
    setDisabling(true);
    try {
      await api.post("/auth/2fa/disable", { code: disableCode });
      toast.success("Two-factor authentication disabled");
      setTotpEnabled(false);
      setDisableCode("");
      // Backup codes are meaningless once 2FA is off.
      setBackupCodes(null);
      setBackupRemaining(null);
      setShowRegen(false);
      setRegenCode("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to disable 2FA");
    } finally {
      setDisabling(false);
    }
  }

  async function handleRegenerate() {
    if (regenCode.length !== 6) return;
    setRegenerating(true);
    try {
      const res = await api.post<BackupCodesResponse>(
        "/auth/2fa/backup-codes/regenerate",
        { code: regenCode },
      );
      setBackupCodes(res.backup_codes);
      setBackupRemaining(res.backup_codes.length);
      setShowRegen(false);
      setRegenCode("");
      toast.success("New backup codes generated — your old codes no longer work");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to regenerate backup codes",
      );
    } finally {
      setRegenerating(false);
    }
  }

  /* ---- Change password handler ---- */
  async function handleChangePassword() {
    if (!currentPassword || !newPassword || !confirmPassword) return;
    if (newPassword.length < 8) {
      toast.error("New password must be at least 8 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("New passwords do not match");
      return;
    }
    setChangingPassword(true);
    try {
      await api.post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success("Password updated successfully");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setChangingPassword(false);
    }
  }

  const passwordFormValid =
    currentPassword.length > 0 &&
    newPassword.length >= 8 &&
    newPassword === confirmPassword;

  return (
    <section className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
      <h2 className="text-lg font-semibold">Security</h2>

      {/* ---- Two-Factor Authentication ---- */}
      <div className="mt-4 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {totpEnabled ? (
              <ShieldCheck className="h-4 w-4 text-green-500" />
            ) : (
              <ShieldOff className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
            )}
            <div>
              <p className="text-sm font-medium">Two-Factor Authentication (2FA)</p>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                {totpEnabled === null
                  ? "Checking status..."
                  : totpEnabled
                    ? "Enabled — a TOTP code is required at login"
                    : "Disabled — add an extra layer of security to your account"}
              </p>
            </div>
          </div>
          {totpEnabled === false && !setup && (
            <button
              onClick={startSetup}
              disabled={setupLoading}
              className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 disabled:opacity-50 transition-colors"
            >
              {setupLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
              Enable 2FA
            </button>
          )}
        </div>

        {/* ---- Setup flow (secret + verify code) ---- */}
        {setup && (
          <div className="space-y-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 p-4">
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              Add this secret to your authenticator app (Google Authenticator, Authy,
              1Password, ...), then enter the 6-digit code it generates to activate 2FA.
            </p>

            <div>
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Secret key
              </label>
              <div className="flex items-center gap-2">
                <code className="flex-1 break-all rounded-md bg-[hsl(var(--background))] px-3 py-2 font-mono text-sm font-semibold tracking-wider">
                  {setup.totp_secret}
                </code>
                <button
                  onClick={() => copyToClipboard(setup.totp_secret, "Secret")}
                  className="rounded-md border border-[hsl(var(--border))] p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                  title="Copy secret"
                >
                  <Copy className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Setup URI (paste into an authenticator that accepts otpauth links)
              </label>
              <div className="flex items-center gap-2">
                <code className="flex-1 break-all rounded-md bg-[hsl(var(--background))] px-3 py-2 font-mono text-[11px] text-[hsl(var(--muted-foreground))]">
                  {setup.totp_uri}
                </code>
                <button
                  onClick={() => copyToClipboard(setup.totp_uri, "Setup URI")}
                  className="rounded-md border border-[hsl(var(--border))] p-2 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                  title="Copy URI"
                >
                  <Copy className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="flex items-end gap-2">
              <div className="flex-1">
                <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                  6-digit code from your app
                </label>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={verifyCode}
                  onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, ""))}
                  placeholder="123456"
                  className={`${inputClass} font-mono tracking-[0.3em]`}
                />
              </div>
              <button
                onClick={handleVerify}
                disabled={verifyCode.length !== 6 || verifying}
                className="inline-flex h-9 items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 disabled:opacity-50 transition-colors"
              >
                {verifying && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Verify &amp; Activate
              </button>
              <button
                onClick={() => {
                  setSetup(null);
                  setVerifyCode("");
                }}
                className="h-9 rounded-md border border-[hsl(var(--border))] px-3 text-sm text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ---- Disable flow ---- */}
        {totpEnabled && (
          <div className="flex items-end gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 p-4">
            <div className="flex-1">
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Enter your current 6-digit code to disable 2FA
              </label>
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ""))}
                placeholder="123456"
                className={`${inputClass} font-mono tracking-[0.3em]`}
              />
            </div>
            <button
              onClick={handleDisable}
              disabled={disableCode.length !== 6 || disabling}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[hsl(var(--destructive))]/30 px-3 text-sm font-medium text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive))]/10 disabled:opacity-50 transition-colors"
            >
              {disabling ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ShieldOff className="h-3.5 w-3.5" />
              )}
              Disable 2FA
            </button>
          </div>
        )}

        {/* ---- Backup codes ---- */}
        {totpEnabled && (
          <div className="space-y-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <KeyRound className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
                <div>
                  <p className="text-sm font-medium">Backup codes</p>
                  <p className="text-xs text-[hsl(var(--muted-foreground))]">
                    {backupRemaining === null
                      ? "One-time codes to sign in if you lose your authenticator"
                      : `${backupRemaining} unused code${backupRemaining === 1 ? "" : "s"} remaining`}
                  </p>
                </div>
              </div>
              {!showRegen && (
                <button
                  onClick={() => {
                    setShowRegen(true);
                    setRegenCode("");
                  }}
                  aria-label="Regenerate backup codes"
                  className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Regenerate codes
                </button>
              )}
            </div>

            {/* Freshly issued codes — shown exactly once */}
            {backupCodes && (
              <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
                <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
                  Save these now — each code works once and they will not be shown again.
                </p>
                <ul
                  className="grid grid-cols-2 gap-1.5 font-mono text-sm"
                  aria-label="Backup codes"
                >
                  {backupCodes.map((c) => (
                    <li
                      key={c}
                      className="rounded bg-[hsl(var(--background))] px-2 py-1 text-center tracking-wider"
                    >
                      {c}
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => copyToClipboard(backupCodes.join("\n"), "Backup codes")}
                    aria-label="Copy all backup codes"
                    className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Copy all
                  </button>
                  <button
                    onClick={() => downloadBackupCodes(backupCodes)}
                    aria-label="Download backup codes as a text file"
                    className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download .txt
                  </button>
                  <button
                    onClick={() => setBackupCodes(null)}
                    aria-label="Dismiss backup codes"
                    className="inline-flex items-center rounded-md px-3 py-1.5 text-xs font-medium text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                  >
                    I&apos;ve saved them
                  </button>
                </div>
              </div>
            )}

            {/* Regenerate flow — requires a current TOTP code */}
            {showRegen && (
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                    Enter a current 6-digit code to replace your backup codes
                  </label>
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={regenCode}
                    onChange={(e) => setRegenCode(e.target.value.replace(/\D/g, ""))}
                    placeholder="123456"
                    aria-label="Current TOTP code for regenerating backup codes"
                    className={`${inputClass} font-mono tracking-[0.3em]`}
                  />
                </div>
                <button
                  onClick={handleRegenerate}
                  disabled={regenCode.length !== 6 || regenerating}
                  aria-label="Confirm regenerate backup codes"
                  className="inline-flex h-9 items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 disabled:opacity-50 transition-colors"
                >
                  {regenerating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Generate
                </button>
                <button
                  onClick={() => {
                    setShowRegen(false);
                    setRegenCode("");
                  }}
                  aria-label="Cancel regenerating backup codes"
                  className="h-9 rounded-md border border-[hsl(var(--border))] px-3 text-sm text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ---- Change Password ---- */}
      <div className="mt-6 border-t border-[hsl(var(--border))] pt-5">
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
          <p className="text-sm font-medium">Change Password</p>
        </div>
        <div className="mt-3 space-y-3">
          <div>
            <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
              Current password
            </label>
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className={inputClass}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                New password
              </label>
              <input
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[hsl(var(--muted-foreground))] mb-1">
                Confirm new password
              </label>
              <input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className={inputClass}
              />
            </div>
          </div>
          {newPassword.length > 0 && newPassword.length < 8 && (
            <p className="text-xs text-[hsl(var(--destructive))]">
              New password must be at least 8 characters.
            </p>
          )}
          {confirmPassword.length > 0 && newPassword !== confirmPassword && (
            <p className="text-xs text-[hsl(var(--destructive))]">
              Passwords do not match.
            </p>
          )}
          <button
            onClick={handleChangePassword}
            disabled={!passwordFormValid || changingPassword}
            className="inline-flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 disabled:opacity-50 transition-colors"
          >
            {changingPassword ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <KeyRound className="h-4 w-4" />
            )}
            Update Password
          </button>
        </div>
      </div>
    </section>
  );
}
