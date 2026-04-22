import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import EmployeesPage from './components/EmployeesPage';
import RfpTaskTable from './components/RfpTaskTable';
import RfpDashboard from './components/RfpDashboard';
import RfpDetail from './components/RfpDetail';
import GlobalProposals from './components/GlobalProposals';
import WorkflowSettings from './components/WorkflowSettings';
import backgroundImg from '../Assets/background.png';

const VALID_PAGES = ['employees', 'rfpdetail', 'proposals', 'globalproposals', 'dashboard', 'settings'];
const DEFAULT_PAGE = 'rfpdetail';

function getPageFromHash() {
  const hash = window.location.hash.replace('#', '').trim();
  return VALID_PAGES.includes(hash) ? hash : null;
}

function App() {
  const [page, setPage] = useState(() => {
    return getPageFromHash() || localStorage.getItem('procurement_page') || DEFAULT_PAGE;
  });
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const pageMeta = {
    employees: {
      title: 'Procurement Team',
      subtitle: 'Choose the right specialist to start requirement capture and sourcing strategy.',
    },
    rfpdetail: {
      title: 'RFP Workspace',
      subtitle: 'Create, refine, score, and export each RFP from one workspace.',
    },
    proposals: {
      title: 'Submission Pipeline',
      subtitle: 'Track active RFPs, incoming proposal files, and next review actions.',
    },
    globalproposals: {
      title: 'Evaluations',
      subtitle: 'Compare vendors, scores, statuses, and summaries across all RFPs.',
    },
    dashboard: {
      title: 'Analytics',
      subtitle: 'Monitor pipeline volume, review progress, and scoring quality.',
    },
    settings: {
      title: 'Workflow Settings',
      subtitle: 'Manage the requester identity and stakeholder directory used by the agent.',
    },
  };

  React.useEffect(() => {
    if (!VALID_PAGES.includes(page)) return;
    localStorage.setItem('procurement_page', page);
    if (window.location.hash !== `#${page}`) {
      window.history.replaceState(null, '', `#${page}`);
    }
  }, [page]);

  React.useEffect(() => {
    const onHashChange = () => {
      const hashPage = getPageFromHash();
      if (hashPage && hashPage !== page) {
        setPage(hashPage);
      }
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [page]);

  return (
    <div
      className="flex min-h-screen"
      style={{
        backgroundImage: `url(${backgroundImg})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      <Sidebar
        currentPage={page}
        onSelectPage={setPage}
        isMobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
      />
      <main className="flex-1 bg-[rgba(244,246,250,0.86)] backdrop-blur-[1px]">
        <div className="border-b border-[#dde3f2] bg-white/80 px-6 py-4 md:px-8">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold text-[#273E91]">{pageMeta[page]?.title || 'Workspace'}</h1>
              <p className="text-sm text-[#5f6b85]">{pageMeta[page]?.subtitle || ''}</p>
            </div>
            <button
              type="button"
              className="rounded-md border border-[#d5dbed] bg-white px-3 py-1 text-sm font-semibold text-[#273E91] hover:bg-[#f2f5fb] lg:hidden"
              onClick={() => setMobileNavOpen(true)}
            >
              Menu
            </button>
          </div>
        </div>
        <div className="px-2 py-2 md:px-4 md:py-4 lg:pl-4">
          {page === 'employees' && <EmployeesPage />}
          {page === 'proposals' && <RfpTaskTable />}
          {page === 'dashboard' && <RfpDashboard />}
          {page === 'rfpdetail' && <RfpDetail />}
          {page === 'globalproposals' && <GlobalProposals />}
          {page === 'settings' && <WorkflowSettings />}
        </div>
      </main>
    </div>
  );
}

export default App;
