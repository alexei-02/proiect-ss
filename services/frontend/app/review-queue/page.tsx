'use client';
import { useEffect, useState, useCallback } from 'react';
import RoleGuard from '@/components/RoleGuard';
import { apiFetch } from '@/lib/api';

interface ReviewDocument {
  document_id: string;
  processed_at: string;
  ocr_engine: string;
  fields: Record<string, { value: string; confidence: number }>;
  low_confidence_fields: string[];
  needs_review: boolean;
}

function ReviewQueueContent() {
  const [docs, setDocs] = useState<ReviewDocument[]>([]);
  const [error, setError] = useState('');
  const [resolving, setResolving] = useState<string | null>(null);

  const fetchQueue = useCallback(async () => {
    try {
      const data = await apiFetch<ReviewDocument[]>('/v1/review-queue');
      setDocs(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to fetch review queue');
    }
  }, []);

  useEffect(() => {
    fetchQueue();
    const interval = setInterval(fetchQueue, 15000);
    return () => clearInterval(interval);
  }, [fetchQueue]);

  async function handleResolve(doc: ReviewDocument) {
    setResolving(doc.document_id);
    try {
      // Approve-as-is: send the existing OCR field values as the "corrected"
      // values. A future iteration can let the doctor edit fields inline before
      // submitting.
      const corrected_fields: Record<string, string> = {};
      for (const [name, ef] of Object.entries(doc.fields ?? {})) {
        corrected_fields[name] = ef.value;
      }
      await apiFetch(`/v1/review-queue/${doc.document_id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ corrected_fields }),
      });
      setDocs(prev => prev.filter(d => d.document_id !== doc.document_id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to resolve document');
    } finally {
      setResolving(null);
    }
  }

  function fieldCount(doc: ReviewDocument): number {
    return Object.keys(doc.fields ?? {}).length;
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-gray-900">Review Queue</h1>
      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-3">Document ID</th>
              <th className="px-4 py-3">Processed At</th>
              <th className="px-4 py-3">Engine</th>
              <th className="px-4 py-3">Low-Confidence Fields</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {docs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-gray-400">
                  No documents pending review.
                </td>
              </tr>
            )}
            {docs.map(doc => (
              <tr key={doc.document_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-xs text-gray-700">
                  {doc.document_id.slice(0, 8)}…
                </td>
                <td className="px-4 py-3 text-gray-500">
                  {new Date(doc.processed_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-gray-700">{doc.ocr_engine}</td>
                <td className="px-4 py-3 text-gray-700">
                  {doc.low_confidence_fields?.join(', ') || `${fieldCount(doc)} fields`}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => handleResolve(doc)}
                    disabled={resolving === doc.document_id}
                    className="rounded-md bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
                  >
                    {resolving === doc.document_id ? 'Approving…' : 'Approve'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-400">Auto-refreshes every 15 seconds.</p>
    </div>
  );
}

export default function ReviewQueuePage() {
  return (
    <RoleGuard roles={['admin', 'doctor', 'receptionist']}>
      <ReviewQueueContent />
    </RoleGuard>
  );
}
