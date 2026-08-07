"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";
import { Plus, Loader2, Pencil, Trash2, Check, X } from "lucide-react";
import { Modal } from "@/components/shared/modal";
import toast from "react-hot-toast";

interface Transaction {
  id: number;
  holding_id: number;
  transaction_type: string;
  date: string;
  quantity: number;
  price: number;
  brokerage: number;
  notes: string | null;
  source: string;
}

/** Which holding's transactions to show. Pass a fresh object per open so the
 * modal re-loads (mirrors the previous inline behavior of loading per click). */
export interface TransactionTarget {
  holdingId: number;
  symbol: string;
  currency: string;
}

interface TransactionHistoryModalProps {
  /** Holding whose transactions to show; null keeps the modal closed. */
  target: TransactionTarget | null;
  onClose: () => void;
  /** Called after any transaction add/edit/delete so the page can refresh holdings. */
  onChanged: () => void | Promise<void>;
}

export function TransactionHistoryModal({ target, onClose, onChanged }: TransactionHistoryModalProps) {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [transLoading, setTransLoading] = useState(false);
  const [addingTrans, setAddingTrans] = useState(false);
  const [transForm, setTransForm] = useState({ type: "BUY", date: "", quantity: 0, price: 0 });
  const [editingTransId, setEditingTransId] = useState<number | null>(null);
  const [editTransForm, setEditTransForm] = useState({ quantity: 0, price: 0 });

  const holdingId = target?.holdingId ?? null;
  const currency = target?.currency ?? "INR";

  // Load transactions whenever a target holding is set.
  useEffect(() => {
    if (holdingId == null) return;
    setTransLoading(true);
    (async () => {
      try {
        // Backfill seed transaction for legacy holdings with no transactions
        await api.post(`/transactions/backfill?holding_id=${holdingId}`).catch(() => {});
        const data = await api.get<Transaction[]>(`/transactions?holding_id=${holdingId}`);
        setTransactions(data);
      } catch {
        toast.error("Failed to load transactions");
        setTransactions([]);
      } finally {
        setTransLoading(false);
      }
    })();
  }, [target, holdingId]);

  async function handleAddTransaction(e: React.FormEvent) {
    e.preventDefault();
    if (!holdingId || !transForm.date || transForm.quantity <= 0 || transForm.price <= 0) {
      toast.error("Please fill in all required fields");
      return;
    }
    setAddingTrans(true);
    try {
      await api.post("/transactions", {
        holding_id: holdingId,
        transaction_type: transForm.type,
        date: transForm.date,
        quantity: transForm.quantity,
        price: transForm.price,
      });
      toast.success(`${transForm.type} transaction added`);
      setTransForm({ type: "BUY", date: "", quantity: 0, price: 0 });
      const data = await api.get<Transaction[]>(`/transactions?holding_id=${holdingId}`);
      setTransactions(data);
      await onChanged();
    } catch {
      toast.error("Failed to add transaction");
    } finally {
      setAddingTrans(false);
    }
  }

  async function handleEditTransaction(txId: number) {
    if (editTransForm.quantity <= 0 || editTransForm.price <= 0) {
      toast.error("Quantity and price must be positive");
      return;
    }
    try {
      await api.patch(`/transactions/${txId}`, {
        quantity: editTransForm.quantity,
        price: editTransForm.price,
      });
      toast.success("Transaction updated");
      setEditingTransId(null);
      if (holdingId) {
        const data = await api.get<Transaction[]>(`/transactions?holding_id=${holdingId}`);
        setTransactions(data);
      }
      await onChanged();
    } catch {
      toast.error("Failed to update transaction");
    }
  }

  async function handleDeleteTransaction(txId: number) {
    if (!confirm("Delete this transaction? The holding will be recalculated.")) return;
    try {
      await api.delete(`/transactions/${txId}`);
      toast.success("Transaction deleted");
      if (holdingId) {
        const data = await api.get<Transaction[]>(`/transactions?holding_id=${holdingId}`);
        setTransactions(data);
      }
      await onChanged();
    } catch {
      toast.error("Failed to delete transaction");
    }
  }

  return (
    <Modal
      open={target != null}
      onClose={onClose}
      title={`Transactions — ${target?.symbol ?? ""}`}
      maxWidth="max-w-2xl"
      cardClassName="max-h-[80vh] overflow-y-auto"
    >
      {/* Add Transaction Form */}
      <form onSubmit={handleAddTransaction} className="mb-4 rounded-lg border border-[hsl(var(--border))] p-4">
        <h3 className="text-sm font-medium mb-3">Add Transaction</h3>
        <div className="grid grid-cols-4 gap-3">
          <div>
            <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Type</label>
            <select
              value={transForm.type}
              onChange={(e) => setTransForm({ ...transForm, type: e.target.value })}
              className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            >
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Date *</label>
            <input
              type="date"
              required
              value={transForm.date}
              onChange={(e) => setTransForm({ ...transForm, date: e.target.value })}
              className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div>
            <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Qty *</label>
            <input
              type="number"
              required
              min="0.000001"
              step="any"
              value={transForm.quantity || ""}
              onChange={(e) => setTransForm({ ...transForm, quantity: parseFloat(e.target.value) || 0 })}
              className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
          <div>
            <label className="block text-xs text-[hsl(var(--muted-foreground))] mb-1">Price *</label>
            <input
              type="number"
              required
              min="0.01"
              step="0.01"
              value={transForm.price || ""}
              onChange={(e) => setTransForm({ ...transForm, price: parseFloat(e.target.value) || 0 })}
              className="h-8 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>
        </div>
        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            disabled={addingTrans}
            className="inline-flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary))]/90 transition-colors disabled:opacity-50"
          >
            {addingTrans ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
            Add Transaction
          </button>
        </div>
      </form>

      {/* Transaction Table */}
      {transLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-md bg-[hsl(var(--muted))]" />
          ))}
        </div>
      ) : transactions.length === 0 ? (
        <p className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
          No transactions recorded yet. Add a buy or sell transaction above.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--muted-foreground))]">
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Date</th>
                <th className="px-4 py-2.5 font-medium text-right">Qty</th>
                <th className="px-4 py-2.5 font-medium text-right">Price</th>
                <th className="px-4 py-2.5 font-medium text-right">Total</th>
                <th className="px-4 py-2.5 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((t) => (
                <tr key={t.id} className="border-b border-[hsl(var(--border))] last:border-0">
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-bold ${
                      t.transaction_type === "BUY"
                        ? "bg-green-500/15 text-green-500"
                        : "bg-red-500/15 text-red-500"
                    }`}>
                      {t.transaction_type}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs">{t.date}</td>
                  {editingTransId === t.id ? (
                    <>
                      <td className="px-4 py-2.5 text-right">
                        <input type="number" min="0.01" step="any" value={editTransForm.quantity || ""}
                          onChange={(e) => setEditTransForm({ ...editTransForm, quantity: parseFloat(e.target.value) || 0 })}
                          className="h-7 w-20 rounded border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-right text-xs font-mono" />
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <input type="number" min="0.01" step="any" value={editTransForm.price || ""}
                          onChange={(e) => setEditTransForm({ ...editTransForm, price: parseFloat(e.target.value) || 0 })}
                          className="h-7 w-24 rounded border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-right text-xs font-mono" />
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">{formatCurrency(editTransForm.quantity * editTransForm.price, currency)}</td>
                      <td className="px-4 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => handleEditTransaction(t.id)} className="rounded p-1 text-green-500 hover:bg-green-500/10" title="Save" aria-label="Save transaction">
                            <Check className="h-3.5 w-3.5" />
                          </button>
                          <button onClick={() => setEditingTransId(null)} className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]" title="Cancel" aria-label="Cancel editing">
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-4 py-2.5 text-right font-mono">{t.quantity}</td>
                      <td className="px-4 py-2.5 text-right font-mono">{formatCurrency(t.price, currency)}</td>
                      <td className="px-4 py-2.5 text-right font-mono">{formatCurrency(t.quantity * t.price, currency)}</td>
                      <td className="px-4 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => { setEditingTransId(t.id); setEditTransForm({ quantity: t.quantity, price: t.price }); }}
                            className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]" title="Edit" aria-label="Edit transaction">
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button onClick={() => handleDeleteTransaction(t.id)}
                            className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:bg-red-500/10 hover:text-red-500" title="Delete" aria-label="Delete transaction">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}
