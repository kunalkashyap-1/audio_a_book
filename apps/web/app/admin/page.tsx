"use client";

/**
 * Phase D admin plane. Every tab reads its data from the typed admin API client; mutations
 * always require a typed reason and are recorded in the server's append-only audit trail.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type {
  AdminAction,
  AdminJob,
  AdminOverview,
  AdminWork,
  FeatureFlag,
  JobEvent,
  ProviderInfo,
} from "@aab/contracts";
import { Header } from "@/components/Header";
import { api, getAdminToken, messageOf } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { shortDate } from "@/lib/format";
import { useHealth } from "@/lib/useHealth";

type Tab = "overview" | "jobs" | "books" | "flags" | "providers";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "jobs", label: "Jobs" },
  { id: "books", label: "Books" },
  { id: "flags", label: "Flags" },
  { id: "providers", label: "Providers" },
];

function fmtValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function isUnauthorized(error: unknown): boolean {
  return Boolean(
    error && typeof error === "object" && "status" in error &&
      (error as { status?: number }).status === 401,
  );
}

function Notice({ error }: { error: string }) {
  if (!error) return null;
  return (
    <p className="mt-4 rounded-lg border border-rose-400/40 bg-rose-400/5 px-4 py-3 text-sm text-rose-300">
      {error}
    </p>
  );
}

function StatusChip({ value }: { value: string }) {
  const tone =
    value === "queued" || value === "running"
      ? "bg-mint-900 text-mint-300"
      : value === "failed" || value === "dead"
        ? "bg-rose-400/20 text-rose-300"
        : "bg-ink-700 text-mist-400";
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] ${tone}`}>{value}</span>;
}

/** Destructive actions require an explicitly typed reason before the button enables. */
function ConfirmAction({
  title,
  detail,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string;
  detail: string;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="panel mt-3 border-gold-400/40 p-4">
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-xs text-mist-400">{detail}</p>
      <input
        className="field mt-3"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Type a reason to confirm"
        aria-label="Reason"
      />
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="btn !bg-rose-400 !text-ink-950 hover:!bg-rose-300"
          disabled={busy || !reason.trim()}
          onClick={() => onConfirm(reason.trim())}
        >
          Confirm
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function Counts({ label, counts }: { label: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  return (
    <div className="panel p-5">
      <h3 className="text-sm font-semibold">{label}</h3>
      {entries.length === 0 ? (
        <p className="mt-2 text-xs text-mist-400">none</p>
      ) : (
        <ul className="mt-3 space-y-1.5 text-sm">
          {entries.map(([key, value]) => (
            <li key={key} className="flex justify-between gap-4">
              <span className="text-mist-400">{key}</span>
              <span className="font-semibold tabular-nums">{value}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- overview

function OverviewTab() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void api.adminOverview().then((value) => {
      if (!cancelled) setOverview(value);
    }).catch((err) => {
      if (!cancelled) setError(isUnauthorized(err)
        ? "Admin access required. Sign in as an admin or set an operator token."
        : messageOf(err));
    });
    return () => { cancelled = true; };
  }, []);

  if (error && !overview) return <Notice error={error} />;
  if (!overview) return <p className="mt-6 text-sm text-mist-400">Loading overview…</p>;

  return (
    <div className="mt-6 space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Counts label="Queue" counts={overview.queue} />
        <Counts label="Jobs by state" counts={overview.jobs_by_state} />
        <Counts label="Works by status" counts={overview.works_by_status} />
        <div className="panel p-5">
          <h3 className="text-sm font-semibold">Accounts</h3>
          <p className="mt-3 text-2xl font-semibold tabular-nums">{overview.users}</p>
          <p className="mt-1 text-xs text-mist-400">registered users</p>
        </div>
      </div>

      <div className="panel p-5">
        <h3 className="text-sm font-semibold">Active provider</h3>
        <p className="mt-2 text-sm">
          {overview.provider.id} · {overview.provider.model_id} v{overview.provider.model_version}
        </p>
        <p className="mt-1 text-xs text-mist-400">{overview.provider.note}</p>
      </div>

      <div className="panel divide-y divide-ink-800 px-5">
        <h3 className="py-4 text-sm font-semibold">Recent admin actions</h3>
        {overview.recent_actions.length === 0 ? (
          <p className="py-4 text-sm text-mist-400">No mutations recorded yet.</p>
        ) : (
          overview.recent_actions.map((action) => (
            <AuditRow key={action.id} action={action} />
          ))
        )}
      </div>
    </div>
  );
}

function AuditRow({ action }: { action: AdminAction }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3 text-sm">
      <span className="font-mono text-xs text-mint-400">{action.action}</span>
      <span className="truncate text-xs text-mist-400">{action.target_id}</span>
      <span className="ml-auto text-xs text-mist-400">
        {action.actor} · {shortDate(action.created_at)}
      </span>
      {action.reason && <span className="w-full text-xs text-mist-300">“{action.reason}”</span>}
    </div>
  );
}

// ---------------------------------------------------------------- jobs

type JobActionKind = "retry" | "cancel";

function JobsTab() {
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [total, setTotal] = useState(0);
  const [state, setState] = useState("");
  const [kind, setKind] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [confirm, setConfirm] = useState<{ job: AdminJob; action: JobActionKind } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = await api.adminJobs({
        state: state || undefined,
        kind: kind || undefined,
        limit: 100,
      });
      setJobs(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, [state, kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (jobId: string) => {
    setDetailId(jobId);
    setError("");
    try {
      const detail = await api.adminJob(jobId);
      setEvents(detail.events);
    } catch (err) {
      setError(messageOf(err));
    }
  };

  const act = async (reason: string) => {
    if (!confirm) return;
    setBusy(true);
    setError("");
    try {
      if (confirm.action === "retry") {
        await api.adminRetryJob(confirm.job.id, { reason });
      } else {
        await api.adminCancelJob(confirm.job.id, { reason });
      }
      setConfirm(null);
      setDetailId(null);
      await load();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-6">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void load();
        }}
      >
        <input
          className="field max-w-40"
          value={state}
          onChange={(event) => setState(event.target.value)}
          placeholder="state (e.g. failed)"
          aria-label="Filter by state"
        />
        <input
          className="field max-w-40"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          placeholder="kind (e.g. render)"
          aria-label="Filter by kind"
        />
        <button type="submit" className="btn-ghost">Apply filters</button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => { setState(""); setKind(""); }}
        >
          Clear
        </button>
        <span className="ml-auto self-center text-xs text-mist-400">{total} job(s)</span>
      </form>

      <Notice error={error} />
      {loading ? (
        <p className="mt-6 text-sm text-mist-400">Loading jobs…</p>
      ) : jobs.length === 0 ? (
        <p className="mt-6 text-sm text-mist-400">No jobs match these filters.</p>
      ) : (
        <div className="panel mt-4 divide-y divide-ink-800 px-5">
          {jobs.map((job) => (
            <div key={job.id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => void openDetail(job.id)}
              >
                <span className="font-mono text-xs text-mint-400">{job.id}</span>
                <span className="ml-2 text-mist-300">{job.kind}</span>
                <span className="ml-2 text-xs text-mist-400">{job.target_id}</span>
              </button>
              <StatusChip value={job.state} />
              <span className="text-xs text-mist-400">
                {job.progress}/{job.total} · {job.attempts}/{job.max_attempts}
              </span>
              {(job.state === "failed" || job.state === "cancelled" || job.state === "dead") && (
                <button
                  type="button"
                  className="btn-ghost !px-2 !py-1 !text-xs"
                  onClick={() => setConfirm({ job, action: "retry" })}
                >
                  Retry
                </button>
              )}
              {(job.state === "queued" || job.state === "failed" || job.state === "dead") && (
                <button
                  type="button"
                  className="btn-ghost !px-2 !py-1 !text-xs hover:!text-rose-300"
                  onClick={() => setConfirm({ job, action: "cancel" })}
                >
                  Cancel
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {confirm && (
        <ConfirmAction
          title={`${confirm.action === "retry" ? "Retry" : "Cancel"} job ${confirm.job.id}`}
          detail={`Current state: ${confirm.job.state}. This writes a job event and an audit row.`}
          busy={busy}
          onConfirm={(reason) => void act(reason)}
          onCancel={() => setConfirm(null)}
        />
      )}

      {detailId && (
        <div className="panel mt-4 p-5">
          <div className="flex items-center justify-between gap-4">
            <h3 className="text-sm font-semibold">Timeline · {detailId}</h3>
            <button type="button" className="text-mist-400 hover:text-mist-100"
                    onClick={() => setDetailId(null)}>
              ✕
            </button>
          </div>
          {events.length === 0 ? (
            <p className="mt-3 text-sm text-mist-400">No events.</p>
          ) : (
            <ul className="mt-3 space-y-2 text-xs">
              {events.map((event, index) => (
                <li key={`${event.created_at}-${index}`} className="flex gap-3">
                  <span className="w-24 shrink-0 font-mono text-mint-400">{event.event}</span>
                  <span className="text-mist-400">{fmtValue(event.detail)}</span>
                  <span className="ml-auto shrink-0 text-mist-400">{shortDate(event.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- books

function BooksTab() {
  const [works, setWorks] = useState<AdminWork[]>([]);
  const [drafts, setDrafts] = useState<Record<string, { shareable: boolean; status: string }>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = await api.adminWorks();
      setWorks(page.items);
      setDrafts(Object.fromEntries(page.items.map((work) => [
        work.id,
        { shareable: work.shareable, status: work.status },
      ])));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async (reason: string) => {
    if (!confirmId) return;
    const draft = drafts[confirmId];
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      await api.adminUpdateWork(confirmId, {
        shareable: draft.shareable,
        status: draft.status,
        reason,
      });
      setConfirmId(null);
      setReasons((previous) => ({ ...previous, [confirmId]: "" }));
      await load();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const changed = (work: AdminWork): boolean => {
    const draft = drafts[work.id];
    return Boolean(draft && (draft.shareable !== work.shareable || draft.status !== work.status));
  };

  return (
    <div className="mt-6">
      <Notice error={error} />
      {loading ? (
        <p className="text-sm text-mist-400">Loading books…</p>
      ) : works.length === 0 ? (
        <p className="text-sm text-mist-400">No books yet.</p>
      ) : (
        <ul className="space-y-2">
          {works.map((work) => {
            const draft = drafts[work.id] ?? { shareable: work.shareable, status: work.status };
            return (
              <li key={work.id} className="panel p-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-semibold">{work.title}</span>
                  <span className="text-xs text-mist-400">
                    {work.author || "Unknown"} · {work.language} · {work.rights_basis}
                  </span>
                  <span className="ml-auto font-mono text-xs text-mist-400">{work.id}</span>
                </div>
                <p className="mt-1 text-xs text-mist-400">
                  {work.chapters} chapter(s) · owner: {work.owner_id || "none"} · created{" "}
                  {shortDate(work.created_at)}
                </p>
                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={draft.shareable}
                      onChange={(event) => setDrafts((previous) => ({
                        ...previous,
                        [work.id]: { ...draft, shareable: event.target.checked },
                      }))}
                    />
                    Shareable
                  </label>
                  <label className="text-sm">
                    <span className="mr-2 text-xs text-mist-400">Status</span>
                    <input
                      className="field !w-32 !py-1"
                      value={draft.status}
                      onChange={(event) => setDrafts((previous) => ({
                        ...previous,
                        [work.id]: { ...draft, status: event.target.value },
                      }))}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn-ghost !py-1 !text-xs"
                    disabled={!changed(work)}
                    onClick={() => setConfirmId(work.id)}
                  >
                    Save changes
                  </button>
                </div>
                {confirmId === work.id && (
                  <ConfirmAction
                    title={`Update ${work.title}`}
                    detail={`shareable: ${String(draft.shareable)} · status: ${draft.status}`}
                    busy={busy}
                    onConfirm={(reason) => void save(reason)}
                    onCancel={() => setConfirmId(null)}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- flags

function FlagsTab() {
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("true");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [deleteKey, setDeleteKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const values = await api.adminFlags();
      setFlags(values);
      setEdits(Object.fromEntries(values.map((flag) => [flag.key, JSON.stringify(flag.value)])));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const setFlag = async (key: string, text: string, reason: string) => {
    let value: unknown;
    try {
      value = JSON.parse(text);
    } catch {
      setError("Flag value must be valid JSON.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.adminSetFlag(key, { value, reason: reason || null });
      await load();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (reason: string) => {
    if (!deleteKey) return;
    setBusy(true);
    setError("");
    try {
      await api.adminDeleteFlag(deleteKey, reason);
      setDeleteKey(null);
      await load();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-6">
      <Notice error={error} />
      <div className="panel p-5">
        <h3 className="text-sm font-semibold">Set a flag</h3>
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!newKey.trim()) return;
            void setFlag(newKey.trim(), newValue, "");
          }}
        >
          <input
            className="field max-w-56"
            value={newKey}
            onChange={(event) => setNewKey(event.target.value)}
            placeholder="flag.key"
            aria-label="Flag key"
          />
          <input
            className="field min-w-48 flex-1 font-mono"
            value={newValue}
            onChange={(event) => setNewValue(event.target.value)}
            placeholder="JSON value"
            aria-label="Flag value"
          />
          <button type="submit" className="btn" disabled={busy || !newKey.trim()}>Set flag</button>
        </form>
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-mist-400">Loading flags…</p>
      ) : flags.length === 0 ? (
        <p className="mt-4 text-sm text-mist-400">No feature flags set.</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {flags.map((flag) => (
            <li key={flag.key} className="panel p-4">
              <div className="flex flex-wrap items-baseline gap-3">
                <span className="font-mono text-sm text-mint-400">{flag.key}</span>
                <span className="text-xs text-mist-400">updated {shortDate(flag.updated_at)}</span>
                <button
                  type="button"
                  className="ml-auto text-xs text-mist-400 hover:text-rose-300"
                  onClick={() => setDeleteKey(flag.key)}
                >
                  Delete
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <textarea
                  className="field min-h-16 flex-1 font-mono"
                  value={edits[flag.key] ?? ""}
                  onChange={(event) => setEdits((previous) => ({
                    ...previous,
                    [flag.key]: event.target.value,
                  }))}
                  aria-label={`Value for ${flag.key}`}
                />
                <button
                  type="button"
                  className="btn-ghost self-start"
                  disabled={busy}
                  onClick={() => void setFlag(flag.key, edits[flag.key] ?? "", "")}
                >
                  Update
                </button>
              </div>
              {deleteKey === flag.key && (
                <ConfirmAction
                  title={`Delete flag ${flag.key}`}
                  detail="This removes the flag and appends a delete action to the audit trail."
                  busy={busy}
                  onConfirm={(reason) => void remove(reason)}
                  onCancel={() => setDeleteKey(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- providers

function ProvidersTab() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void api.adminProviders().then((values) => {
      if (!cancelled) setProviders(values);
    }).catch((err) => {
      if (!cancelled) setError(messageOf(err));
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="mt-6">
      <Notice error={error} />
      <p className="text-sm text-mist-400">
        Read-only registry. Switching providers is a deployment change, not an admin action.
      </p>
      {loading ? (
        <p className="mt-4 text-sm text-mist-400">Loading providers…</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {providers.map((provider) => (
            <li key={provider.id} className="panel p-4">
              <div className="flex flex-wrap items-baseline gap-3">
                <span className="font-semibold">{provider.id}</span>
                <span className="text-xs text-mist-400">
                  {provider.model_id} · v{provider.model_version} · {provider.presets} presets
                </span>
                {provider.active && <span className="badge ml-auto">active</span>}
              </div>
              <p className="mt-2 text-xs text-mist-400">{provider.note}</p>
              <pre className="mt-3 overflow-x-auto rounded-lg bg-ink-950 p-3 text-[11px] text-mist-300">
                {JSON.stringify(provider.capabilities, null, 2)}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- page shell

export default function AdminPage() {
  const health = useHealth();
  const { user, authEnabled, ready } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");

  const needsCredential = ready && authEnabled && user?.role !== "admin" && !getAdminToken();

  return (
    <div className="min-h-screen">
      <Header health={health} />
      <main className="mx-auto max-w-5xl p-6">
        <h1 className="text-2xl font-semibold">Administration</h1>
        <p className="mt-1 text-sm text-mist-400">
          Queue operations, catalogue controls and runtime flags. Every mutation is audited.
        </p>

        {needsCredential && (
          <p className="mt-4 rounded-lg border border-gold-400/40 bg-gold-400/5 px-4 py-3 text-sm text-gold-400">
            This instance has accounts enabled. Admin routes need an admin account or an
            operator token — sign in as an admin, or set one in the catalogue page.
          </p>
        )}

        <nav className="mt-6 flex flex-wrap gap-1 border-b border-ink-800" aria-label="Admin sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
                tab === item.id
                  ? "border-mint-400 text-mint-300"
                  : "border-transparent text-mist-400 hover:text-mist-100"
              }`}
              aria-current={tab === item.id ? "page" : undefined}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {tab === "overview" && <OverviewTab />}
        {tab === "jobs" && <JobsTab />}
        {tab === "books" && <BooksTab />}
        {tab === "flags" && <FlagsTab />}
        {tab === "providers" && <ProvidersTab />}

        <Link href="/" className="link mt-8 inline-block text-sm">
          Back to the catalogue →
        </Link>
      </main>
    </div>
  );
}
