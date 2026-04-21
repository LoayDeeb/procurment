import React, { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../config/api';
import { apiClient, formatApiError } from '../config/http';

function scoreValue(score) {
  if (score === null || score === undefined) return '-';
  return Number(score).toFixed(1);
}

export default function GlobalProposals() {
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [rfpFilter, setRfpFilter] = useState('all');
  const [vendorFilter, setVendorFilter] = useState('');
  const [scoreMin, setScoreMin] = useState('');
  const [scoreMax, setScoreMax] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  useEffect(() => {
    fetchProposals();
  }, []);

  const fetchProposals = async () => {
    setLoading(true);
    try {
      setError('');
      const res = await apiClient.get('/proposals');
      setProposals(res.data || []);
    } catch (err) {
      setProposals([]);
      setError(`Unable to load proposal portfolio. ${formatApiError(err, `Verify backend is running at ${API_BASE}.`)}`);
    } finally {
      setLoading(false);
    }
  };

  const rfpOptions = useMemo(() => {
    return Array.from(new Set(proposals.map((p) => p.rfp_name))).filter(Boolean);
  }, [proposals]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const v = vendorFilter.trim().toLowerCase();
    const min = scoreMin === '' ? null : Number(scoreMin);
    const max = scoreMax === '' ? null : Number(scoreMax);

    return proposals.filter((proposal) => {
      const vendor = (proposal.vendor || '').toLowerCase();
      const rfpName = (proposal.rfp_name || '').toLowerCase();
      const status = proposal.status || (proposal.score !== null && proposal.score !== undefined ? 'Scored' : 'Pending');
      const score = proposal.score !== null && proposal.score !== undefined ? Number(proposal.score) : null;

      const matchesRfp = rfpFilter === 'all' || proposal.rfp_name === rfpFilter;
      const matchesVendor = !v || vendor.includes(v);
      const matchesStatus = statusFilter === 'all' || status === statusFilter;
      const matchesSearch =
        !q ||
        `${proposal.rfp_name || ''} ${proposal.vendor || ''} ${proposal.report || ''}`.toLowerCase().includes(q);
      const matchesMin = min === null || (score !== null && score >= min);
      const matchesMax = max === null || (score !== null && score <= max);

      return matchesRfp && matchesVendor && matchesStatus && matchesSearch && matchesMin && matchesMax;
    });
  }, [proposals, rfpFilter, vendorFilter, scoreMin, scoreMax, statusFilter, search]);

  return (
    <div className="min-h-screen w-full bg-[#f4f6fa] px-4 py-6 md:px-8">
      <div className="mx-auto max-w-[1300px] space-y-5">
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        <div className="rounded-xl border border-[#e7eaf3] bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-bold text-[#273E91]">All Proposals</h2>
              <p className="text-sm text-[#5f6b85]">Compare vendors, scores, and reports across the full procurement portfolio.</p>
            </div>
            <button
              onClick={fetchProposals}
              className="rounded-lg bg-[#273E91] px-4 py-2 text-sm font-semibold text-white hover:bg-[#20357d]"
            >
              Refresh
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
            <input
              placeholder="Search vendor, RFP, or summary"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91]"
              aria-label="Search proposals"
            />
            <select
              value={rfpFilter}
              onChange={(e) => setRfpFilter(e.target.value)}
              className="rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91]"
              aria-label="Filter by RFP"
            >
              <option value="all">All RFPs</option>
              {rfpOptions.map((rfpName) => (
                <option key={rfpName} value={rfpName}>
                  {rfpName}
                </option>
              ))}
            </select>
            <input
              placeholder="Vendor"
              value={vendorFilter}
              onChange={(e) => setVendorFilter(e.target.value)}
              className="rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91]"
              aria-label="Filter by vendor"
            />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91]"
              aria-label="Filter by status"
            >
              <option value="all">All Statuses</option>
              <option value="Pending">Pending</option>
              <option value="Scored">Scored</option>
            </select>
            <input
              placeholder="Score min"
              type="number"
              value={scoreMin}
              onChange={(e) => setScoreMin(e.target.value)}
              className="rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91]"
              aria-label="Minimum score"
            />
            <input
              placeholder="Score max"
              type="number"
              value={scoreMax}
              onChange={(e) => setScoreMax(e.target.value)}
              className="rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91]"
              aria-label="Maximum score"
            />
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-[#e7eaf3] bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse">
              <thead className="bg-[#f7f9fd]">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">RFP</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Vendor</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Uploaded</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Score</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Status</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Summary</th>
                  <th className="px-4 py-3 text-right text-sm font-semibold text-[#273E91]">Files</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-sm text-[#5f6b85]">
                      Loading proposals...
                    </td>
                  </tr>
                ) : filtered.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-sm text-[#7a8399]">
                      No proposals match the selected filters.
                    </td>
                  </tr>
                ) : (
                  filtered.map((proposal) => {
                    const status =
                      proposal.status || (proposal.score !== null && proposal.score !== undefined ? 'Scored' : 'Pending');
                    return (
                      <tr key={proposal.id} className="border-t border-[#eff2f8]">
                        <td className="px-4 py-3 font-semibold text-[#273E91]">{proposal.rfp_name || '-'}</td>
                        <td className="px-4 py-3 text-sm text-[#2f3650]">{proposal.vendor || '-'}</td>
                        <td className="px-4 py-3 text-sm text-[#5f6b85]">
                          {proposal.upload_date ? new Date(proposal.upload_date).toLocaleString() : '-'}
                        </td>
                        <td className="px-4 py-3 text-sm font-semibold text-[#00A5AF]">
                          {proposal.score === null || proposal.score === undefined ? '-' : `${scoreValue(proposal.score)}/100`}
                        </td>
                        <td className="px-4 py-3 text-sm font-semibold text-[#273E91]">{status}</td>
                        <td className="max-w-[300px] truncate px-4 py-3 text-sm text-[#4e5670]" title={proposal.report || '-'}>
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
                            {proposal.score !== null && proposal.score !== undefined ? (
                              <a
                                href={`${API_BASE}/proposals/${proposal.id}/evaluation-pdf`}
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
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
