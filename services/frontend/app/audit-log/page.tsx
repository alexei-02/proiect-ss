'use client';
import { useEffect, useState, useCallback } from 'react';
import RoleGuard from '@/components/RoleGuard';
import { apiFetch } from '@/lib/api';

interface AuditEntry {
  id: number;
  occurred_at: string;
  username: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  outcome: string;
}

interface AuditResponse {
  entries: AuditEntry[];
  next_cursor: number | null;
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

function AuditLogContent() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [cursorStack, setCursorStack] = useState<(number | null)[]>([null]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [pageSize, setPageSize] = useState<number>(10);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchLog = useCallback(
    async (cursor: number | null, limit: number) => {
      setLoading(true);
      try {
        const qs = new URLSearchParams({ limit: String(limit) });
        if (cursor !== null) qs.set('cursor', String(cursor));
        const data = await apiFetch<AuditResponse>(`/v1/audit-log?${qs}`);
        setEntries(data.entries ?? []);
        setNextCursor(data.next_cursor);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to fetch audit log');
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    fetchLog(cursorStack[cursorStack.length - 1], pageSize);
  }, [fetchLog, cursorStack, pageSize]);

  function changePageSize(n: number) {
    // Switching page size resets pagination to the first page.
    setPageSize(n);
    setCursorStack([null]);
  }

  const page = cursorStack.length;
  const hasPrev = page > 1;
  const hasNext = nextCursor !== null;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-gray-900">Audit Log</h1>
      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="max-h-[60vh] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 shadow-sm">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Resource</th>
                <th className="px-4 py-3">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {entries.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-gray-400">
                    {loading ? 'Loading…' : 'No audit log entries.'}
                  </td>
                </tr>
              )}
              {entries.map(entry => (
                <tr key={entry.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {new Date(entry.occurred_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-gray-700">{entry.username ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-700">{entry.action}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">
                    {entry.resource_type
                      ? `${entry.resource_type}:${(entry.resource_id ?? '').slice(0, 8)}…`
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        entry.outcome === 'success'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-red-100 text-red-800'
                      }`}
                    >
                      {entry.outcome}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
        <div className="flex items-center gap-2">
          <label htmlFor="page-size" className="text-gray-600">
            Rows per page:
          </label>
          <select
            id="page-size"
            value={pageSize}
            onChange={e => changePageSize(Number(e.target.value))}
            className="rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {PAGE_SIZE_OPTIONS.map(n => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-3">
          <span>Page {page}</span>
          <div className="flex gap-2">
            <button
              onClick={() => setCursorStack(prev => prev.slice(0, -1))}
              disabled={!hasPrev || loading}
              className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-40 transition-colors"
            >
              Prev
            </button>
            <button
              onClick={() => setCursorStack(prev => [...prev, nextCursor])}
              disabled={!hasNext || loading}
              className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-40 transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AuditLogPage() {
  return (
    <RoleGuard roles={['admin', 'auditor']}>
      <AuditLogContent />
    </RoleGuard>
  );
}
