import React, { useEffect, useMemo, useState } from 'react';
import ProposalTable from './ProposalTable';
import ProposalModal from './ProposalModal';
import { API_BASE } from '../config/api';
import { apiClient, formatApiError } from '../config/http';

const PAGE_SIZE = 8;

function normalizeRfpText(value) {
  return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();
}

function getRfpDedupKey(rfp) {
  const nameKey = normalizeRfpText(rfp?.name);
  const requirementsKey = normalizeRfpText(rfp?.requirements);
  if (nameKey && requirementsKey) {
    return `requirements:${nameKey}:${requirementsKey}`;
  }

  const filenameKey = normalizeRfpText(rfp?.pdf_filename);
  if (nameKey && filenameKey) {
    return `file:${nameKey}:${filenameKey}`;
  }

  return `row:${rfp?.id ?? ''}`;
}

function pickPreferredRfp(current, candidate) {
  const currentProposalCount = Number(current?.proposal_count ?? -1);
  const candidateProposalCount = Number(candidate?.proposal_count ?? -1);
  if (candidateProposalCount !== currentProposalCount) {
    return candidateProposalCount > currentProposalCount ? candidate : current;
  }

  const currentHasSource = Boolean(current?.pdf_filename);
  const candidateHasSource = Boolean(candidate?.pdf_filename);
  if (currentHasSource !== candidateHasSource) {
    return candidateHasSource ? candidate : current;
  }

  return Number(candidate?.id ?? 0) > Number(current?.id ?? 0) ? candidate : current;
}

export default function RfpTaskTable() {
  const [rfps, setRfps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [openProposalRfp, setOpenProposalRfp] = useState(null);
  const [uploadRfp, setUploadRfp] = useState(null);
  const [search, setSearch] = useState('');
  const [pageNum, setPageNum] = useState(1);

  useEffect(() => {
    fetchRfps();
  }, []);

  useEffect(() => {
    setPageNum(1);
  }, [search]);

  const fetchRfps = async () => {
    setLoading(true);
    try {
      setError('');
      const res = await apiClient.get('/rfps');
      setRfps(res.data || []);
    } catch (err) {
      setRfps([]);
      setError(`Unable to load RFPs. ${formatApiError(err, `Verify backend is running at ${API_BASE}.`)}`);
    } finally {
      setLoading(false);
    }
  };

  const uniqueRfps = useMemo(() => {
    const deduped = new Map();
    rfps.forEach((rfp) => {
      const key = getRfpDedupKey(rfp);
      const existing = deduped.get(key);
      deduped.set(key, existing ? pickPreferredRfp(existing, rfp) : rfp);
    });
    return Array.from(deduped.values()).sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
  }, [rfps]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return uniqueRfps;
    return uniqueRfps.filter((rfp) => (rfp.name || '').toLowerCase().includes(q));
  }, [uniqueRfps, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(pageNum, totalPages);
  const paged = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  return (
    <div className="w-full min-h-screen bg-[#f4f6fa] px-4 py-6 md:px-8">
      <div className="mx-auto max-w-[1300px]">
        {error ? (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        <div className="mb-5 rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-bold text-[#273E91]">RFP Submissions</h2>
              <p className="text-sm text-[#5f6b85]">Manage incoming submissions and open evaluation results by RFP.</p>
            </div>
            <div className="flex w-full gap-2 md:w-auto">
              <input
                placeholder="Search RFP title"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91] md:w-72"
                aria-label="Search RFPs"
              />
              <button
                onClick={() => {
                  setSearch('');
                  setPageNum(1);
                }}
                className="rounded-lg border border-[#d6dbea] bg-white px-3 py-2 text-sm font-semibold text-[#273E91] hover:bg-[#f2f5fb]"
              >
                Reset
              </button>
            </div>
          </div>
        </div>

        {uploadRfp ? (
          <div className="mb-5">
            <ProposalModal
              embedded
              rfp={uploadRfp}
              onClose={() => setUploadRfp(null)}
              onComplete={() => {
                fetchRfps();
                setOpenProposalRfp(uploadRfp.id);
              }}
            />
          </div>
        ) : null}

        {openProposalRfp ? (
          <div className="mb-5">
            <ProposalTable embedded rfpId={openProposalRfp} onClose={() => setOpenProposalRfp(null)} />
          </div>
        ) : null}

        <div className="overflow-hidden rounded-xl border border-[#e7eaf3] bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse">
              <thead className="bg-[#f7f9fd]">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">RFP Name</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Status</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Submission Count</th>
                  <th className="px-4 py-3 text-right text-sm font-semibold text-[#273E91]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-sm text-[#5f6b85]">
                      Loading RFPs...
                    </td>
                  </tr>
                ) : paged.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-sm text-[#7a8399]">
                      No RFPs found.
                    </td>
                  </tr>
                ) : (
                  paged.map((rfp) => (
                    <tr key={rfp.id} className="border-t border-[#eff2f8]">
                      <td className="px-4 py-3 font-semibold text-[#273E91]">{rfp.name || `RFP ${rfp.id}`}</td>
                      <td className="px-4 py-3 text-sm text-[#4e5670]">{rfp.status || 'Waiting for Proposal'}</td>
                      <td className="px-4 py-3 text-sm font-semibold text-[#273E91]">
                        {rfp.proposal_count !== undefined ? rfp.proposal_count : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <button
                            className="rounded-lg bg-[#00BEC9] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#00a9b2]"
                            onClick={() => setUploadRfp(rfp)}
                          >
                            Upload
                          </button>
                          <button
                            className="rounded-lg bg-[#273E91] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#20357d]"
                            onClick={() => setOpenProposalRfp(rfp.id)}
                          >
                            Review
                          </button>
                          {rfp.pdf_filename ? (
                            <a
                              href={`${API_BASE}/download/${rfp.pdf_filename}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded-lg border border-[#d4daeb] px-3 py-1.5 text-sm font-semibold text-[#273E91] hover:bg-[#f2f5fb]"
                            >
                              Source RFP
                            </a>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            onClick={() => setPageNum(1)}
            disabled={safePage === 1}
            className="rounded-md border border-[#d4daeb] bg-white px-3 py-1 text-sm font-semibold text-[#273E91] disabled:cursor-not-allowed disabled:opacity-50"
          >
            First
          </button>
          <button
            onClick={() => setPageNum(Math.max(1, safePage - 1))}
            disabled={safePage === 1}
            className="rounded-md border border-[#d4daeb] bg-white px-3 py-1 text-sm font-semibold text-[#273E91] disabled:cursor-not-allowed disabled:opacity-50"
          >
            Prev
          </button>
          <span className="px-2 text-sm text-[#4e5670]">
            Page {safePage} of {totalPages}
          </span>
          <button
            onClick={() => setPageNum(Math.min(totalPages, safePage + 1))}
            disabled={safePage === totalPages}
            className="rounded-md border border-[#d4daeb] bg-white px-3 py-1 text-sm font-semibold text-[#273E91] disabled:cursor-not-allowed disabled:opacity-50"
          >
            Next
          </button>
          <button
            onClick={() => setPageNum(totalPages)}
            disabled={safePage === totalPages}
            className="rounded-md border border-[#d4daeb] bg-white px-3 py-1 text-sm font-semibold text-[#273E91] disabled:cursor-not-allowed disabled:opacity-50"
          >
            Last
          </button>
        </div>

        
      </div>
    </div>
  );
}
