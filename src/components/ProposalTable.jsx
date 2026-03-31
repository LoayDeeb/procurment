import React, { useEffect, useState } from 'react';
import { API_BASE } from '../config/api';
import { apiClient, formatApiError } from '../config/http';

export default function ProposalTable({ rfpId, onClose, embedded = false }) {
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (rfpId) fetchProposals();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rfpId]);

  const fetchProposals = async () => {
    setLoading(true);
    try {
      setError('');
      const res = await apiClient.get(`/rfps/${rfpId}/proposals`);
      setProposals(res.data || []);
    } catch (err) {
      setProposals([]);
      setError(`Unable to load proposals. ${formatApiError(err, `Verify backend is running at ${API_BASE}.`)}`);
    } finally {
      setLoading(false);
    }
  };

  const content = (
      <div className={`relative w-full overflow-hidden rounded-xl border border-[#e7eaf3] bg-white ${embedded ? 'shadow-sm' : 'max-h-[85vh] max-w-6xl shadow-xl'}`}>
        <div className="flex items-center justify-between border-b border-[#eef1f8] px-5 py-4">
          <h3 className="text-lg font-bold text-[#273E91]">Proposal Review - RFP #{rfpId}</h3>
          <button
            onClick={onClose}
            className="rounded-md border border-[#d5dbed] px-3 py-1 text-sm font-semibold text-[#273E91] hover:bg-[#f2f5fb]"
            aria-label="Close proposals dialog"
          >
            Close
          </button>
        </div>

        <div className={`${embedded ? '' : 'max-h-[calc(85vh-70px)]'} overflow-auto`}>
          {loading ? (
            <div className="px-6 py-10 text-center text-sm text-[#5f6b85]">Loading proposals...</div>
          ) : error ? (
            <div className="px-6 py-10 text-center text-sm text-red-700">{error}</div>
          ) : proposals.length === 0 ? (
            <div className="px-6 py-10 text-center text-sm text-[#7a8399]">No proposals submitted yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] border-collapse">
                <thead className="bg-[#f7f9fd]">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Vendor</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Uploaded</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Score</th>
                    <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Summary</th>
                    <th className="px-4 py-3 text-right text-sm font-semibold text-[#273E91]">Files</th>
                  </tr>
                </thead>
                <tbody>
                  {proposals.map((proposal) => (
                    <tr key={proposal.id} className="border-t border-[#eff2f8]">
                      <td className="px-4 py-3 text-sm font-semibold text-[#273E91]">{proposal.vendor || '-'}</td>
                      <td className="px-4 py-3 text-sm text-[#5f6b85]">
                        {proposal.upload_date ? new Date(proposal.upload_date).toLocaleString() : '-'}
                      </td>
                      <td className="px-4 py-3 text-sm font-semibold text-[#00A5AF]">
                        {proposal.score !== null && proposal.score !== undefined
                          ? `${Number(proposal.score).toFixed(1)}/100`
                          : '-'}
                      </td>
                      <td className="max-w-[420px] truncate px-4 py-3 text-sm text-[#4e5670]" title={proposal.report || '-'}>
                        {proposal.report || '-'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <a
                            href={`${API_BASE}/proposals/${proposal.id}/download`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="rounded-lg border border-[#d4daeb] px-3 py-1.5 text-xs font-semibold text-[#273E91] hover:bg-[#f2f5fb]"
                          >
                            Source
                          </a>
                          {proposal.pdf_summary ? (
                            <a
                              href={`${API_BASE}/pdfs/${proposal.pdf_summary}`}
                              target="_blank"
                              rel="noopener noreferrer"
                            className="rounded-lg bg-[#273E91] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#20357d]"
                          >
                            Evaluation PDF
                          </a>
                          ) : (
                            <span className="rounded-lg border border-[#eceff8] px-3 py-1.5 text-xs text-[#7a8399]">Not ready</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
  );

  if (embedded) {
    return content;
  }

  return <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/45 p-4">{content}</div>;
}
