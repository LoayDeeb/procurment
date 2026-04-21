import React, { useEffect, useMemo, useState } from 'react';
import ProposalModal from './ProposalModal';
import { API_BASE } from '../config/api';
import { apiClient, formatApiError } from '../config/http';

function scoreLabel(value) {
  if (value === null || value === undefined) return '-';
  return `${Number(value).toFixed(1)}/100`;
}

export default function RfpDetail() {
  const [tab, setTab] = useState('overview');
  const [rfps, setRfps] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [selectedRfpId, setSelectedRfpId] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [loadingRfps, setLoadingRfps] = useState(true);
  const [loadingProposals, setLoadingProposals] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchRfps();
  }, []);

  useEffect(() => {
    if (selectedRfpId) {
      fetchProposals(selectedRfpId);
    } else {
      setProposals([]);
    }
  }, [selectedRfpId]);

  const fetchRfps = async () => {
    setLoadingRfps(true);
    try {
      setError('');
      const res = await apiClient.get('/rfps');
      const workflowRes = await apiClient.get('/workflow/rfp-requests');
      const items = res.data || [];
      setRfps(items);
      setWorkflows(workflowRes.data || []);
      if (items.length) {
        setSelectedRfpId((prev) => prev ?? items[0].id);
      } else {
        setSelectedRfpId(null);
      }
    } catch (err) {
      setError(`Unable to load RFP workspace. ${formatApiError(err, `Verify backend is running at ${API_BASE}.`)}`);
      setRfps([]);
      setWorkflows([]);
      setSelectedRfpId(null);
    } finally {
      setLoadingRfps(false);
    }
  };

  const fetchProposals = async (rfpId) => {
    setLoadingProposals(true);
    try {
      const res = await apiClient.get(`/rfps/${rfpId}/proposals`);
      setProposals(res.data || []);
    } catch (err) {
      setProposals([]);
      setError(`Unable to load proposal records for RFP ${rfpId}. ${formatApiError(err, 'Please retry.')}`);
    } finally {
      setLoadingProposals(false);
    }
  };

  const selectedRfp = useMemo(() => {
    return rfps.find((rfp) => rfp.id === selectedRfpId) || null;
  }, [rfps, selectedRfpId]);

  const analytics = useMemo(() => {
    const scored = proposals.filter((proposal) => proposal.score !== null && proposal.score !== undefined);
    const avgScore = scored.length
      ? (scored.reduce((sum, proposal) => sum + Number(proposal.score || 0), 0) / scored.length).toFixed(1)
      : '-';
    const best = scored.length
      ? scored.reduce((top, current) => (Number(current.score) > Number(top.score) ? current : top))
      : null;
    const pendingCount = proposals.length - scored.length;

    return { scoredCount: scored.length, avgScore, best, pendingCount };
  }, [proposals]);

  return (
    <div className="min-h-screen w-full bg-[#f4f6fa] px-4 py-6 md:px-8">
      <div className="mx-auto max-w-[1300px] space-y-5">
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        <div className="rounded-xl border border-[#e7eaf3] bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-lg font-bold text-[#273E91]">RFP Detail</h2>
              <p className="text-sm text-[#5f6b85]">Run one RFP end-to-end: submissions, evaluation, and decision support.</p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
              <select
                value={selectedRfpId || ''}
                onChange={(e) => setSelectedRfpId(Number(e.target.value))}
                disabled={loadingRfps || rfps.length === 0}
                className="w-full rounded-lg border border-[#d6dbea] px-3 py-2 text-sm outline-none focus:border-[#273E91] sm:w-80"
                aria-label="Select RFP"
              >
                {loadingRfps ? <option value="">Loading RFPs...</option> : null}
                {!loadingRfps && rfps.length === 0 ? <option value="">No RFPs available</option> : null}
                {rfps.map((rfp) => (
                  <option key={rfp.id} value={rfp.id}>
                    {rfp.name || `RFP ${rfp.id}`}
                  </option>
                ))}
              </select>
              <button
                onClick={() => selectedRfp && setShowUploadModal(true)}
                disabled={!selectedRfp}
                className="rounded-lg bg-[#273E91] px-4 py-2 text-sm font-semibold text-white hover:bg-[#20357d] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Add Submission
              </button>
            </div>
          </div>
        </div>

        {selectedRfp ? (
          <>
            <div className="rounded-xl border border-[#e7eaf3] bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => setTab('overview')}
                  className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${
                    tab === 'overview' ? 'bg-[#273E91] text-white' : 'bg-[#eef2fa] text-[#273E91] hover:bg-[#e3eaf8]'
                  }`}
                >
                  Overview
                </button>
                <button
                  onClick={() => setTab('proposals')}
                  className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${
                    tab === 'proposals' ? 'bg-[#273E91] text-white' : 'bg-[#eef2fa] text-[#273E91] hover:bg-[#e3eaf8]'
                  }`}
                >
                  Proposals
                </button>
                <button
                  onClick={() => setTab('analytics')}
                  className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${
                    tab === 'analytics' ? 'bg-[#273E91] text-white' : 'bg-[#eef2fa] text-[#273E91] hover:bg-[#e3eaf8]'
                  }`}
                >
                  Analytics
                </button>
              </div>
            </div>

            {showUploadModal ? (
              <ProposalModal
                embedded
                rfp={selectedRfp}
                onClose={() => setShowUploadModal(false)}
                onComplete={() => {
                  setShowUploadModal(false);
                  fetchRfps();
                  fetchProposals(selectedRfp.id);
                }}
              />
            ) : null}

            {tab === 'overview' ? (
              <div className="rounded-xl border border-[#e7eaf3] bg-white p-5 shadow-sm">
                <div className="mb-5">
                  <h3 className="text-xl font-bold text-[#273E91]">{selectedRfp.name || `RFP ${selectedRfp.id}`}</h3>
                  <p className="mt-2 text-sm text-[#5f6b85]">{selectedRfp.status || 'Waiting for Proposal'}</p>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div className="rounded-lg border border-[#edf0f8] p-4">
                    <p className="text-sm text-[#5f6b85]">Total Proposals</p>
                    <p className="mt-1 text-2xl font-bold text-[#273E91]">{proposals.length}</p>
                  </div>
                  <div className="rounded-lg border border-[#edf0f8] p-4">
                    <p className="text-sm text-[#5f6b85]">Scored</p>
                    <p className="mt-1 text-2xl font-bold text-[#273E91]">{analytics.scoredCount}</p>
                  </div>
                  <div className="rounded-lg border border-[#edf0f8] p-4">
                    <p className="text-sm text-[#5f6b85]">Average Score</p>
                    <p className="mt-1 text-2xl font-bold text-[#00A5AF]">
                      {analytics.avgScore === '-' ? '-' : `${analytics.avgScore}/100`}
                    </p>
                  </div>
                </div>

                <div className="mt-5 space-y-2">
                  <p className="text-sm font-semibold text-[#273E91]">RFP Source File</p>
                  {selectedRfp.pdf_filename ? (
                    <a
                      href={`${API_BASE}/download/${selectedRfp.pdf_filename}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex rounded-lg border border-[#d4daeb] px-3 py-1.5 text-sm font-semibold text-[#273E91] hover:bg-[#f2f5fb]"
                    >
                      Download Source RFP
                    </a>
                  ) : (
                    <p className="text-sm text-[#7a8399]">No RFP source file available for this record.</p>
                  )}
                </div>

                <div className="mt-5 rounded-lg border border-[#edf0f8] p-4">
                  <p className="text-sm font-semibold text-[#273E91]">Stakeholder Workflows</p>
                  {workflows.length === 0 ? (
                    <p className="mt-2 text-sm text-[#7a8399]">No stakeholder-driven RFP workflows yet.</p>
                  ) : (
                    <div className="mt-3 space-y-2">
                      {workflows.slice(0, 5).map((workflow) => (
                        <div key={workflow.id} className="rounded-lg border border-[#edf0f8] px-3 py-2 text-sm">
                          <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                            <span className="font-semibold text-[#273E91]">{workflow.title}</span>
                            <span className="text-[#5f6b85]">{workflow.workflow_status}</span>
                          </div>
                          <p className="mt-1 text-[#5f6b85]">
                            {workflow.requester_name}  -  {workflow.requester_email}
                          </p>
                          {workflow.final_pdf_url ? (
                            <a
                              href={`${API_BASE}${workflow.final_pdf_url}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-2 inline-flex rounded-lg border border-[#d4daeb] px-3 py-1.5 text-xs font-semibold text-[#273E91] hover:bg-[#f2f5fb]"
                            >
                              Open Final Workflow PDF
                            </a>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : null}

            {tab === 'proposals' ? (
              <div className="overflow-hidden rounded-xl border border-[#e7eaf3] bg-white shadow-sm">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[960px] border-collapse">
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
                      {loadingProposals ? (
                        <tr>
                          <td colSpan={5} className="px-4 py-10 text-center text-sm text-[#5f6b85]">
                            Loading proposals...
                          </td>
                        </tr>
                      ) : proposals.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="px-4 py-10 text-center text-sm text-[#7a8399]">
                            No proposals uploaded yet for this RFP.
                          </td>
                        </tr>
                      ) : (
                        proposals.map((proposal) => (
                          <tr key={proposal.id} className="border-t border-[#eff2f8]">
                            <td className="px-4 py-3 text-sm font-semibold text-[#273E91]">{proposal.vendor || '-'}</td>
                            <td className="px-4 py-3 text-sm text-[#5f6b85]">
                              {proposal.upload_date ? new Date(proposal.upload_date).toLocaleString() : '-'}
                            </td>
                            <td className="px-4 py-3 text-sm font-semibold text-[#00A5AF]">{scoreLabel(proposal.score)}</td>
                            <td className="max-w-[360px] truncate px-4 py-3 text-sm text-[#4e5670]" title={proposal.report || '-'}>
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
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}

            {tab === 'analytics' ? (
              <div className="rounded-xl border border-[#e7eaf3] bg-white p-5 shadow-sm">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div className="rounded-lg border border-[#edf0f8] p-4">
                    <p className="text-sm text-[#5f6b85]">Scored Proposals</p>
                    <p className="mt-1 text-2xl font-bold text-[#273E91]">{analytics.scoredCount}</p>
                  </div>
                  <div className="rounded-lg border border-[#edf0f8] p-4">
                    <p className="text-sm text-[#5f6b85]">Pending Scoring</p>
                    <p className="mt-1 text-2xl font-bold text-[#273E91]">{analytics.pendingCount}</p>
                  </div>
                  <div className="rounded-lg border border-[#edf0f8] p-4">
                    <p className="text-sm text-[#5f6b85]">Average Score</p>
                    <p className="mt-1 text-2xl font-bold text-[#00A5AF]">
                      {analytics.avgScore === '-' ? '-' : `${analytics.avgScore}/100`}
                    </p>
                  </div>
                </div>

                <div className="mt-5 rounded-lg border border-[#edf0f8] p-4">
                  <p className="text-sm font-semibold text-[#273E91]">Top Proposal</p>
                  {analytics.best ? (
                    <p className="mt-1 text-sm text-[#2f3650]">
                      {analytics.best.vendor || '-'} with score {scoreLabel(analytics.best.score)}
                    </p>
                  ) : (
                    <p className="mt-1 text-sm text-[#7a8399]">No scored proposals yet.</p>
                  )}
                </div>
              </div>
            ) : null}
          </>
        ) : (
          <div className="rounded-xl border border-[#e7eaf3] bg-white px-5 py-10 text-center text-sm text-[#7a8399] shadow-sm">
            {loadingRfps ? 'Loading RFP details...' : 'No RFPs available yet.'}
          </div>
        )}

      </div>
    </div>
  );
}
