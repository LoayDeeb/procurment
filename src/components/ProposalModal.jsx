import React, { useState } from 'react';
import { apiClient, formatApiError } from '../config/http';

export default function ProposalModal({ rfp, onClose, onComplete, embedded = false }) {
  const [file, setFile] = useState(null);
  const [vendor, setVendor] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState('idle');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) return;

    setProgress('uploading');
    setSubmitting(true);
    setError('');

    try {
      const formData = new FormData();
      formData.append('file', file);
      const trimmedVendor = vendor.trim();

      const uploadRes = await apiClient.post(`/rfps/${rfp.id}/proposals`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        params: trimmedVendor ? { vendor: trimmedVendor } : undefined,
        timeout: 120000,
      });

      setProgress('scoring');
      const scoreFormData = new FormData();
      scoreFormData.append('file', file);
      await apiClient.post(`/rfps/${rfp.id}/score`, scoreFormData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        params: { proposal_id: uploadRes.data.id },
        timeout: 300000,
      });

      const proposalId = uploadRes.data.id;
      let attempts = 0;
      const maxAttempts = 20;
      let scored = false;

      while (!scored && attempts < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        attempts += 1;
        const checkRes = await apiClient.get(`/proposals/${proposalId}`);
        if (checkRes.data && checkRes.data.score !== null && checkRes.data.score !== undefined) {
          scored = true;
        }
      }

      setProgress('complete');
      setSubmitting(false);
      if (onComplete) onComplete();
    } catch (err) {
      setProgress('idle');
      setSubmitting(false);
      setError(formatApiError(err, 'Upload failed. Please try again.'));
    }
  };

  const content = (
    <div className={`relative w-full rounded-xl border border-[#e7eaf3] bg-white p-6 ${embedded ? 'shadow-sm' : 'max-w-xl shadow-xl'}`}>
        <button
          onClick={onClose}
          disabled={submitting}
          className="absolute right-4 top-4 rounded-md border border-[#d5dbed] px-3 py-1 text-sm font-semibold text-[#273E91] hover:bg-[#f2f5fb] disabled:cursor-not-allowed disabled:opacity-60"
          aria-label="Close upload dialog"
        >
          Close
        </button>

        <h3 className="mb-5 text-lg font-bold text-[#273E91]">Submit Proposal for {rfp.name || `RFP ${rfp.id}`}</h3>

        {error ? (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        ) : null}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-semibold text-[#2f3650]">Vendor Name (Optional)</label>
            <input
              type="text"
              value={vendor}
              onChange={(e) => setVendor(e.target.value)}
              placeholder="e.g. Jordan Tech Supplies"
              className="w-full rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91]"
              disabled={submitting}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-semibold text-[#2f3650]">Proposal File (PDF)</label>
            <input
              type="file"
              accept=".pdf,application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              required
              disabled={submitting}
              className="block w-full rounded-lg border border-[#d6dbea] bg-white px-3 py-2 text-sm text-[#2f3650]"
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !file}
            className="w-full rounded-lg bg-[#273E91] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#20357d] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? 'Submitting...' : 'Submit and Evaluate'}
          </button>
        </form>

        <div className="mt-4 min-h-6 text-sm">
          {progress === 'uploading' ? <div className="text-[#273E91]">Uploading proposal...</div> : null}
          {progress === 'scoring' ? <div className="text-[#273E91]">Running AI evaluation...</div> : null}
          {progress === 'complete' ? (
            <div className="font-semibold text-[#00A5AF]">Proposal uploaded and scoring completed.</div>
          ) : null}
        </div>
      </div>
  );

  if (embedded) {
    return content;
  }

  return <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/45 p-4">{content}</div>;
}
