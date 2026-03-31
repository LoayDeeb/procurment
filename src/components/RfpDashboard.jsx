import React, { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../config/api';
import { apiClient, formatApiError } from '../config/http';

function formatScore(value) {
  if (value === null || value === undefined) return '-';
  return Number(value).toFixed(1);
}

export default function RfpDashboard() {
  const [rfps, setRfps] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      setError('');
      const [rfpRes, proposalRes] = await Promise.all([
        apiClient.get('/rfps'),
        apiClient.get('/proposals'),
      ]);
      setRfps(rfpRes.data || []);
      setProposals(proposalRes.data || []);
    } catch (err) {
      setRfps([]);
      setProposals([]);
      setError(`Unable to load dashboard data. ${formatApiError(err, `Verify backend is running at ${API_BASE}.`)}`);
    } finally {
      setLoading(false);
    }
  };

  const proposalCountByRfp = useMemo(() => {
    const counts = {};
    proposals.forEach((proposal) => {
      const key = proposal.rfp_id;
      counts[key] = (counts[key] || 0) + 1;
    });
    return counts;
  }, [proposals]);

  const enrichedRfps = useMemo(() => {
    return rfps.map((rfp) => {
      const count = proposalCountByRfp[rfp.id] ?? rfp.proposal_count ?? 0;
      const derivedStatus = count > 0 ? 'In Review' : 'Waiting for Proposal';
      return {
        ...rfp,
        proposal_count: count,
        derived_status: rfp.status || derivedStatus,
      };
    });
  }, [rfps, proposalCountByRfp]);

  const filteredRfps = useMemo(() => {
    const q = search.trim().toLowerCase();
    return enrichedRfps.filter((rfp) => {
      const matchesSearch = !q || (rfp.name || '').toLowerCase().includes(q);
      const matchesStatus = statusFilter === 'all' || rfp.derived_status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [enrichedRfps, search, statusFilter]);

  const metrics = useMemo(() => {
    const totalRfps = enrichedRfps.length;
    const totalProposals = proposals.length;
    const scored = proposals.filter((proposal) => proposal.score !== null && proposal.score !== undefined);
    const avgScore = scored.length
      ? (scored.reduce((sum, proposal) => sum + Number(proposal.score || 0), 0) / scored.length).toFixed(1)
      : '-';
    return { totalRfps, totalProposals, scoredCount: scored.length, avgScore };
  }, [enrichedRfps, proposals]);

  const highestProposals = useMemo(() => {
    return proposals
      .filter((proposal) => proposal.score !== null && proposal.score !== undefined)
      .sort((a, b) => Number(b.score) - Number(a.score))
      .slice(0, 5);
  }, [proposals]);

  const statuses = useMemo(() => {
    const unique = new Set(enrichedRfps.map((rfp) => rfp.derived_status).filter(Boolean));
    return ['all', ...Array.from(unique)];
  }, [enrichedRfps]);

  return (
    <div className="min-h-screen w-full bg-[#f4f6fa] px-4 py-6 md:px-8">
      <div className="mx-auto max-w-[1300px] space-y-5">
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        <div className="rounded-xl border border-[#e7eaf3] bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-bold text-[#273E91]">RFP Analytics Dashboard</h2>
              <p className="text-sm text-[#5f6b85]">Track sourcing pipeline health, submission volume, and evaluation quality.</p>
            </div>
            <button
              onClick={fetchData}
              className="rounded-lg bg-[#273E91] px-4 py-2 text-sm font-semibold text-white hover:bg-[#20357d]"
            >
              Refresh
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
            <p className="text-sm text-[#5f6b85]">Total RFPs</p>
            <p className="mt-1 text-2xl font-bold text-[#273E91]">{metrics.totalRfps}</p>
          </div>
          <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
            <p className="text-sm text-[#5f6b85]">Total Proposals</p>
            <p className="mt-1 text-2xl font-bold text-[#273E91]">{metrics.totalProposals}</p>
          </div>
          <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
            <p className="text-sm text-[#5f6b85]">Scored Proposals</p>
            <p className="mt-1 text-2xl font-bold text-[#273E91]">{metrics.scoredCount}</p>
          </div>
          <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
            <p className="text-sm text-[#5f6b85]">Average Score</p>
            <p className="mt-1 text-2xl font-bold text-[#00A5AF]">{metrics.avgScore === '-' ? '-' : `${metrics.avgScore}/100`}</p>
          </div>
        </div>

        <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row">
            <input
              placeholder="Search RFP title"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91] md:w-72"
              aria-label="Search RFPs"
            />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91] md:w-64"
              aria-label="Filter by status"
            >
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status === 'all' ? 'All statuses' : status}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-[#e7eaf3] bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse">
              <thead className="bg-[#f7f9fd]">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">RFP</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Status</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Proposals</th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-[#273E91]">Best Score</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-sm text-[#5f6b85]">
                      Loading dashboard...
                    </td>
                  </tr>
                ) : filteredRfps.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-sm text-[#7a8399]">
                      No RFPs match the current filters.
                    </td>
                  </tr>
                ) : (
                  filteredRfps.map((rfp) => {
                    const rfpProposals = proposals.filter((proposal) => proposal.rfp_id === rfp.id);
                    const bestScore = rfpProposals.length
                      ? Math.max(...rfpProposals.map((proposal) => Number(proposal.score || 0)))
                      : null;
                    return (
                      <tr key={rfp.id} className="border-t border-[#eff2f8]">
                        <td className="px-4 py-3 font-semibold text-[#273E91]">{rfp.name || `RFP ${rfp.id}`}</td>
                        <td className="px-4 py-3 text-sm text-[#4e5670]">{rfp.derived_status}</td>
                        <td className="px-4 py-3 text-sm font-semibold text-[#273E91]">{rfp.proposal_count}</td>
                        <td className="px-4 py-3 text-sm font-semibold text-[#00A5AF]">
                          {bestScore === null ? '-' : `${formatScore(bestScore)}/100`}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
          <h3 className="mb-3 text-base font-semibold text-[#273E91]">Top Scored Proposals</h3>
          {highestProposals.length === 0 ? (
            <p className="text-sm text-[#7a8399]">No scored proposals yet.</p>
          ) : (
            <div className="space-y-2">
              {highestProposals.map((proposal) => (
                <div
                  key={proposal.id}
                  className="flex flex-col justify-between rounded-lg border border-[#edf0f8] px-3 py-2 text-sm md:flex-row md:items-center"
                >
                  <span className="font-semibold text-[#273E91]">
                    {proposal.vendor || '-'}  -  {proposal.rfp_name || `RFP ${proposal.rfp_id}`}
                  </span>
                  <span className="font-semibold text-[#00A5AF]">{formatScore(proposal.score)}/100</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

