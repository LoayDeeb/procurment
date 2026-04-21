import React, { useEffect, useState } from 'react';
import { apiClient, formatApiError } from '../config/http';

function emptyStakeholder() {
  return { role: '', name: '', email: '' };
}

export default function WorkflowSettings() {
  const [requesterName, setRequesterName] = useState('');
  const [requesterEmail, setRequesterEmail] = useState('');
  const [stakeholders, setStakeholders] = useState([emptyStakeholder()]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [statusMeta, setStatusMeta] = useState({ workflow_ready: false, gmail_configured: false });

  const loadConfig = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiClient.get('/workflow/config');
      const data = res.data || {};
      setRequesterName(data.requester_name || '');
      setRequesterEmail(data.requester_email || '');
      setStakeholders(Array.isArray(data.stakeholders) && data.stakeholders.length ? data.stakeholders : [emptyStakeholder()]);
      setStatusMeta({
        workflow_ready: Boolean(data.workflow_ready),
        gmail_configured: Boolean(data.gmail_configured),
      });
    } catch (err) {
      setError(formatApiError(err, 'Unable to load workflow settings.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  const updateStakeholder = (index, field, value) => {
    setStakeholders((prev) =>
      prev.map((item, itemIndex) => (itemIndex === index ? { ...item, [field]: value } : item))
    );
  };

  const addStakeholder = () => {
    setStakeholders((prev) => [...prev, emptyStakeholder()]);
  };

  const removeStakeholder = (index) => {
    setStakeholders((prev) => {
      const next = prev.filter((_, itemIndex) => itemIndex !== index);
      return next.length ? next : [emptyStakeholder()];
    });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    setSuccess('');

    const cleanedStakeholders = stakeholders
      .map((item) => ({
        role: item.role.trim(),
        name: item.name.trim(),
        email: item.email.trim(),
      }))
      .filter((item) => item.role && item.name && item.email);

    if (!requesterName.trim() || !requesterEmail.trim()) {
      setSaving(false);
      setError('Requester name and requester email are required.');
      return;
    }

    if (!cleanedStakeholders.length) {
      setSaving(false);
      setError('Add at least one stakeholder with role, name, and email.');
      return;
    }

    try {
      const res = await apiClient.put('/workflow/config', {
        requester_name: requesterName.trim(),
        requester_email: requesterEmail.trim(),
        stakeholders: cleanedStakeholders,
      });
      const data = res.data || {};
      setStakeholders(Array.isArray(data.stakeholders) && data.stakeholders.length ? data.stakeholders : [emptyStakeholder()]);
      setStatusMeta({
        workflow_ready: Boolean(data.workflow_ready),
        gmail_configured: Boolean(data.gmail_configured),
      });
      setSuccess('Workflow settings saved.');
    } catch (err) {
      setError(formatApiError(err, 'Unable to save workflow settings.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl p-4 md:p-6">
      <div className="rounded-3xl border border-[#d6def2] bg-white/90 p-6 shadow-[0_18px_40px_rgba(39,62,145,0.10)]">
        <div className="flex flex-col gap-3 border-b border-[#e5eaf7] pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-2xl font-bold text-[#22367f]">Workflow Settings</h2>
            <p className="mt-1 text-sm text-[#5f6b85]">
              Set the static requester identity and stakeholder directory used by the procurement agent.
            </p>
          </div>
          <div className="grid gap-2 text-xs md:text-right">
            <span className={`rounded-full px-3 py-1 font-semibold ${statusMeta.gmail_configured ? 'bg-[#e9f8f1] text-[#0a8f66]' : 'bg-[#fff4e8] text-[#b96a00]'}`}>
              {statusMeta.gmail_configured ? 'Gmail Configured' : 'Gmail Missing'}
            </span>
            <span className={`rounded-full px-3 py-1 font-semibold ${statusMeta.workflow_ready ? 'bg-[#eef4ff] text-[#273E91]' : 'bg-[#fff1f1] text-[#c7372f]'}`}>
              {statusMeta.workflow_ready ? 'Workflow Ready' : 'Workflow Incomplete'}
            </span>
          </div>
        </div>

        {loading ? (
          <div className="py-8 text-sm text-[#5f6b85]">Loading workflow settings...</div>
        ) : (
          <form className="space-y-6 pt-6" onSubmit={handleSubmit}>
            <section className="rounded-2xl border border-[#e5eaf7] bg-[#f9fbff] p-4">
              <h3 className="text-sm font-bold uppercase tracking-[0.08em] text-[#60709c]">Requester</h3>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm text-[#33426f]">
                  <span className="font-semibold">Requester Name</span>
                  <input
                    value={requesterName}
                    onChange={(e) => setRequesterName(e.target.value)}
                    className="rounded-xl border border-[#c7d5f3] bg-white px-4 py-3 outline-none focus:border-[#6e89d8] focus:ring-2 focus:ring-[#d9e4ff]"
                    placeholder="Procurement Officer"
                  />
                </label>
                <label className="grid gap-2 text-sm text-[#33426f]">
                  <span className="font-semibold">Requester Email</span>
                  <input
                    type="email"
                    value={requesterEmail}
                    onChange={(e) => setRequesterEmail(e.target.value)}
                    className="rounded-xl border border-[#c7d5f3] bg-white px-4 py-3 outline-none focus:border-[#6e89d8] focus:ring-2 focus:ring-[#d9e4ff]"
                    placeholder="procurement@company.com"
                  />
                </label>
              </div>
            </section>

            <section className="rounded-2xl border border-[#e5eaf7] bg-[#f9fbff] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-bold uppercase tracking-[0.08em] text-[#60709c]">Stakeholders</h3>
                  <p className="mt-1 text-xs text-[#5f6b85]">These contacts are the fixed people the agent emails for requirements.</p>
                </div>
                <button
                  type="button"
                  onClick={addStakeholder}
                  className="rounded-xl border border-[#c5d3f2] bg-white px-4 py-2 text-sm font-semibold text-[#273E91] hover:bg-[#f3f7ff]"
                >
                  Add Stakeholder
                </button>
              </div>

              <div className="mt-4 space-y-4">
                {stakeholders.map((stakeholder, index) => (
                  <div key={`${index}-${stakeholder.role}-${stakeholder.email}`} className="grid gap-3 rounded-2xl border border-[#dde5f7] bg-white p-4 md:grid-cols-[1fr_1fr_1.3fr_auto]">
                    <input
                      value={stakeholder.role}
                      onChange={(e) => updateStakeholder(index, 'role', e.target.value)}
                      className="rounded-xl border border-[#c7d5f3] px-4 py-3 text-sm outline-none focus:border-[#6e89d8] focus:ring-2 focus:ring-[#d9e4ff]"
                      placeholder="Role"
                    />
                    <input
                      value={stakeholder.name}
                      onChange={(e) => updateStakeholder(index, 'name', e.target.value)}
                      className="rounded-xl border border-[#c7d5f3] px-4 py-3 text-sm outline-none focus:border-[#6e89d8] focus:ring-2 focus:ring-[#d9e4ff]"
                      placeholder="Name"
                    />
                    <input
                      type="email"
                      value={stakeholder.email}
                      onChange={(e) => updateStakeholder(index, 'email', e.target.value)}
                      className="rounded-xl border border-[#c7d5f3] px-4 py-3 text-sm outline-none focus:border-[#6e89d8] focus:ring-2 focus:ring-[#d9e4ff]"
                      placeholder="email@company.com"
                    />
                    <button
                      type="button"
                      onClick={() => removeStakeholder(index)}
                      className="rounded-xl border border-[#f1c8c8] bg-[#fff7f7] px-4 py-3 text-sm font-semibold text-[#b43c3c] hover:bg-[#fff1f1]"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            </section>

            {error ? <div className="rounded-xl border border-[#f0c9c9] bg-[#fff5f5] px-4 py-3 text-sm text-[#b43c3c]">{error}</div> : null}
            {success ? <div className="rounded-xl border border-[#ccebd8] bg-[#effaf4] px-4 py-3 text-sm text-[#0a8f66]">{success}</div> : null}

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={saving}
                className="rounded-xl bg-[#273E91] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#20357d] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? 'Saving...' : 'Save Workflow Settings'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
