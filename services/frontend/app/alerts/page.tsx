'use client';
import { useEffect, useState, useCallback } from 'react';
import RoleGuard from '@/components/RoleGuard';
import { apiFetch } from '@/lib/api';

interface Alert {
  id: string;
  type: string;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  expires_at: string | null;
  acknowledged: boolean;
}

const SEVERITY_BADGE: Record<string, string> = {
  info: 'bg-blue-100 text-blue-800',
  warning: 'bg-yellow-100 text-yellow-800',
  critical: 'bg-red-100 text-red-800',
};

function AlertsContent() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [error, setError] = useState('');
  const [acking, setAcking] = useState<string | null>(null);

  const fetchAlerts = useCallback(async () => {
    try {
      const data = await apiFetch<Alert[]>('/v1/alerts');
      setAlerts(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to fetch alerts');
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  async function handleAcknowledge(id: string) {
    setAcking(id);
    try {
      await apiFetch(`/v1/alerts/${id}/acknowledge`, { method: 'POST' });
      setAlerts(prev => prev.map(a => (a.id === id ? { ...a, acknowledged: true } : a)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to acknowledge alert');
    } finally {
      setAcking(null);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Alerts</h1>
        <button
          onClick={fetchAlerts}
          className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors"
        >
          Refresh
        </button>
      </div>
      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Severity</th>
              <th className="px-4 py-3">Message</th>
              <th className="px-4 py-3">Expires On</th>
              <th className="px-4 py-3">Acknowledged</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {alerts.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-400">
                  No alerts.
                </td>
              </tr>
            )}
            {alerts.map(alert => (
              <tr key={alert.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-700">{alert.type}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${SEVERITY_BADGE[alert.severity] ?? 'bg-gray-100 text-gray-700'}`}
                  >
                    {alert.severity}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-700">{alert.message}</td>
                <td className="px-4 py-3 text-gray-500">
                  {alert.expires_at ? new Date(alert.expires_at).toLocaleString() : '—'}
                </td>
                <td className="px-4 py-3">
                  {alert.acknowledged ? (
                    <span className="text-green-600 font-medium">Yes</span>
                  ) : (
                    <span className="text-gray-400">No</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {!alert.acknowledged && (
                    <button
                      onClick={() => handleAcknowledge(alert.id)}
                      disabled={acking === alert.id}
                      className="rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                    >
                      {acking === alert.id ? 'Acking…' : 'Acknowledge'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AlertsPage() {
  return (
    <RoleGuard roles={['admin', 'doctor', 'auditor']}>
      <AlertsContent />
    </RoleGuard>
  );
}
