import React from 'react';

export default function Sidebar({ currentPage, onSelectPage, isMobileOpen, onCloseMobile }) {
  const navSections = [
    {
      title: 'Core Workflow',
      caption: 'Move from intake to scoring with a clear sourcing flow.',
      items: [
        {
          key: 'employees',
          label: 'Team Directory',
          description: 'Start requirement capture with the right procurement specialist.',
          icon: 'users',
        },
        {
          key: 'rfpdetail',
          label: 'RFP Workspace',
          description: 'Create, refine, score, and export each RFP from one place.',
          icon: 'clipboard',
        },
        {
          key: 'proposals',
          label: 'Submission Pipeline',
          description: 'Track open RFPs, incoming bids, and review actions.',
          icon: 'inbox',
        },
        {
          key: 'globalproposals',
          label: 'Evaluations',
          description: 'Compare vendor scores, reports, and status across all RFPs.',
          icon: 'file-stack',
        },
        {
          key: 'dashboard',
          label: 'Analytics',
          description: 'Monitor pipeline volume and overall evaluation quality.',
          icon: 'chart',
        },
      ],
    },
    {
      title: 'Administration',
      caption: 'Maintain the shared defaults used by the procurement agent.',
      items: [
        {
          key: 'settings',
          label: 'Workflow Settings',
          description: 'Manage requester identity and stakeholder contact details.',
          icon: 'gear',
        },
      ],
    },
  ];

  const renderIcon = (type) => {
    if (type === 'users') {
      return (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 0 0 3.741-.479 3 3 0 0 0-4.682-2.72m.94 3.198.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0 1 12 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 0 1 6 18.719m12 0a5.971 5.971 0 0 0-.941-3.197m0 0A5.995 5.995 0 0 0 12 12.75a5.995 5.995 0 0 0-5.058 2.772m0 0a3 3 0 0 0-4.681 2.72 8.986 8.986 0 0 0 3.74.477m.94-3.197a5.971 5.971 0 0 0-.94 3.197M15 6.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
        </svg>
      );
    }
    if (type === 'clipboard') {
      return (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5.25H7.5A2.25 2.25 0 0 0 5.25 7.5v10.5A2.25 2.25 0 0 0 7.5 20.25h9A2.25 2.25 0 0 0 18.75 18V7.5A2.25 2.25 0 0 0 16.5 5.25H15m-6 0a2.25 2.25 0 0 1 2.25-2.25h1.5A2.25 2.25 0 0 1 15 5.25m-6 0A2.25 2.25 0 0 0 11.25 7.5h1.5A2.25 2.25 0 0 0 15 5.25m-6 6h6m-6 3h6" />
        </svg>
      );
    }
    if (type === 'inbox') {
      return (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 9.776c0-.49.19-.961.53-1.312l2.757-2.848A2.25 2.25 0 0 1 8.655 4.95h6.69c.604 0 1.182.244 1.606.676l2.757 2.849c.34.35.53.82.53 1.311v7.714A2.25 2.25 0 0 1 18 19.75H6A2.25 2.25 0 0 1 3.75 17.5V9.776Zm.75 5.724h4.44a.75.75 0 0 0 .67-.414l.59-1.172a.75.75 0 0 1 .67-.414h2.26a.75.75 0 0 1 .67.414l.59 1.172a.75.75 0 0 0 .67.414h4.44" />
        </svg>
      );
    }
    if (type === 'file-plus') {
      return (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 10.5v6m3-3h-6m7.5 6.75H6.75A2.25 2.25 0 0 1 4.5 18V6A2.25 2.25 0 0 1 6.75 3.75h6.88a2.25 2.25 0 0 1 1.59.659l2.87 2.871c.422.422.659.995.659 1.591V18a2.25 2.25 0 0 1-2.25 2.25Z" />
        </svg>
      );
    }
    if (type === 'file-stack') {
      return (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625A1.125 1.125 0 0 0 4.5 3.375v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
        </svg>
      );
    }
    if (type === 'chart') {
      return (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.5h4.5V21H3v-7.5Zm6.75-9h4.5V21h-4.5V4.5Zm6.75 4.5H21V21h-4.5V9Z" />
        </svg>
      );
    }
    return (
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor" className="h-5 w-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
      </svg>
    );
  };

  const classes = [
    'w-72 flex-shrink-0 overflow-y-auto border-r border-[#243053] bg-[#192038] transition-all duration-300',
    'fixed inset-y-0 left-0 z-40 lg:static lg:translate-x-0',
    isMobileOpen ? 'translate-x-0' : '-translate-x-full',
  ].join(' ');

  return (
    <>
      {isMobileOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          aria-label="Close navigation menu"
          onClick={onCloseMobile}
        />
      ) : null}
      <aside className={classes}>
      <div className="p-5">
        <div className="mb-6 rounded-2xl border border-[#2c385d] bg-[#1e2743] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[#8f9bc0]">Procurement Demo</p>
          <p className="mt-1 text-sm font-bold text-white">Sourcing Command Center</p>
          <p className="mt-2 text-xs leading-5 text-[#a6b0d0]">
            Follow the procurement workflow from intake to evaluation without losing context.
          </p>
        </div>
        <div className="space-y-5">
          {navSections.map((section) => (
            <div key={section.title}>
              <div className="mb-2 px-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#8f9bc0]">{section.title}</p>
                <p className="mt-1 text-xs leading-5 text-[#7f8aad]">{section.caption}</p>
              </div>
              <nav className="space-y-2">
                {section.items.map((item) => {
                  const isActive = currentPage === item.key;
                  return (
                    <button
                      key={item.key}
                      className={`group flex w-full items-start gap-3 rounded-2xl border px-3 py-3 text-left transition-all duration-200 ${
                        isActive
                          ? 'border-[#3c56b5] bg-[#243472] text-white shadow-[0_14px_26px_rgba(10,18,52,0.26)]'
                          : 'border-transparent text-[#d0d6ea] hover:border-[#2d3d6a] hover:bg-[#202a47] hover:text-white'
                      }`}
                      aria-current={isActive ? 'page' : undefined}
                      onClick={() => {
                        onSelectPage(item.key);
                        if (onCloseMobile) onCloseMobile();
                      }}
                    >
                      <span
                        className={`mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl border ${
                          isActive
                            ? 'border-white/15 bg-white/10 text-white'
                            : 'border-[#31406b] bg-[#1b2440] text-[#9eabcf] group-hover:border-[#405282] group-hover:text-white'
                        }`}
                      >
                        {renderIcon(item.icon)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="text-sm font-semibold tracking-[0.01em]">{item.label}</span>
                          {isActive ? (
                            <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[#d5deff]">
                              Current
                            </span>
                          ) : null}
                        </span>
                        <span className={`mt-1 block text-xs leading-5 ${
                          isActive ? 'text-[#dbe3ff]' : 'text-[#8f9bc0] group-hover:text-[#c9d2ee]'
                        }`}>
                          {item.description}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </nav>
            </div>
          ))}
        </div>
      </div>
      </aside>
    </>
  );
}
