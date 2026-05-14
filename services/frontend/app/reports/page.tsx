'use client';
import { useState, FormEvent } from 'react';
import RoleGuard from '@/components/RoleGuard';
import { apiFetch } from '@/lib/api';

const REPORT_TYPES = [
  { value: 'ocr_summary', label: 'OCR Summary' },
  { value: 'audit_export', label: 'Audit Export' },
  { value: 'compliance', label: 'Compliance' },
  { value: 'anonymised_export', label: 'Anonymised Export' },
];

interface Report {
  id: string;
  report_type: string;
  status: string;
  created_at: string;
}

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  processing: 'bg-blue-100 text-blue-800',
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

function ReportsContent() {
  const [reportType, setReportType] = useState(REPORT_TYPES[0].value);
  const [reports, setReports] = useState<Report[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      const data = await apiFetch<Report>('/v1/reports', {
        method: 'POST',
        body: JSON.stringify({ report_type: reportType }),
      });
      setReports(prev => [data, ...prev]);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create report');
    } finally {
      setSubmitting(false);
    }
  }

  async function checkStatus(id: string) {
    try {
      const data = await apiFetch<Report>(`/v1/reports/${id}/status`);
      setReports(prev => prev.map(r => (r.id === id ? { ...r, status: data.status } : r)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to check status');
    }
  }

  async function downloadReport(id: string) {
    // <a download> can't attach the Authorization header, so the API returns
    // 401 and the browser saves the JSON error. Fetch the file as a blob with
    // the Bearer token, then trigger the download via an object URL.
    try {
      const token = document.cookie.match(/access_token=([^;]+)/)?.[1] ?? '';
      const res = await fetch(`/api/v1/reports/${id}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report_${id}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Download failed');
    }
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-gray-900">Reports</h1>

      {/* Request new report */}
      <div className="mb-8 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-gray-800">Request New Report</h2>
        <form onSubmit={handleSubmit} className="flex items-end gap-4">
          <div className="flex-1">
            <label className="mb-1 block text-sm font-medium text-gray-700" htmlFor="report-type">
              Report Type
            </label>
            <select
              id="report-type"
              value={reportType}
              onChange={e => setReportType(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {REPORT_TYPES.map(rt => (
                <option key={rt.value} value={rt.value}>
                  {rt.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Requesting…' : 'Request Report'}
          </button>
        </form>
        {error && (
          <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        )}
      </div>

      {/* Report list */}
      {reports.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-4 py-3">Report ID</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created At</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {reports.map(report => (
                <tr key={report.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">
                    {report.id.slice(0, 8)}…
                  </td>
                  <td className="px-4 py-3 text-gray-700">{report.report_type}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[report.status] ?? 'bg-gray-100 text-gray-700'}`}
                    >
                      {report.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {new Date(report.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 flex items-center gap-2">
                    <button
                      onClick={() => checkStatus(report.id)}
                      className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100 transition-colors"
                    >
                      Refresh
                    </button>
                    {report.status === 'ready' && (
                      <button
                        onClick={() => downloadReport(report.id)}
                        className="rounded-md bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 transition-colors"
                      >
                        Download
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function ReportsPage() {
  return (
    <RoleGuard roles={['admin', 'auditor']}>
      <ReportsContent />
    </RoleGuard>
  );
}
