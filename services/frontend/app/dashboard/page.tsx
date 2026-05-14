'use client';
import { useEffect, useState, useCallback } from 'react';
import RoleGuard from '@/components/RoleGuard';
import MetricCard from '@/components/MetricCard';
import { apiFetch } from '@/lib/api';

interface OcrMetrics {
  review_queue_depth: number;
  completed_last_24h: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
}

function DashboardContent() {
  const [metrics, setMetrics] = useState<OcrMetrics | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchMetrics = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiFetch<OcrMetrics>('/v1/metrics/ocr');
      setMetrics(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to fetch metrics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
        <button
          onClick={fetchMetrics}
          disabled={loading}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}
      {metrics ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="Review Queue Depth" value={metrics.review_queue_depth} />
          <MetricCard label="Completed last 24h" value={metrics.completed_last_24h} />
          <MetricCard label="P50 Latency (ms)" value={metrics.p50_latency_ms} />
          <MetricCard label="P95 Latency (ms)" value={metrics.p95_latency_ms} />
        </div>
      ) : !loading && (
        <p className="text-sm text-gray-500">No metrics available.</p>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RoleGuard roles={['admin', 'auditor']}>
      <DashboardContent />
    </RoleGuard>
  );
}
