import React, { useState } from 'react';
import EmployeeCard from './EmployeeCard';
import ChatPage from './ChatPage';

import img1 from '../../Assets/img1.png';
import img2 from '../../Assets/img2.png';
import img3 from '../../Assets/img3.png';
import bg1 from '../../Assets/bg1.png';
import bg2 from '../../Assets/bg2.png';
import bg3 from '../../Assets/bg3.png';

const employees = [
  {
    name: 'Ahmad Al-Khatib',
    title: 'Procurement Operations Lead',
    img: img1,
    bg: bg1,
    avatar: img1,
    initial: 'A',
  },
  {
    name: 'Mohammad Haddad',
    title: 'Strategic Sourcing Specialist',
    img: img2,
    bg: bg2,
    avatar: img2,
    initial: 'M',
  },
  {
    name: 'Jumana Nasser',
    title: 'Vendor Performance Analyst',
    img: img3,
    bg: bg3,
    avatar: img3,
    initial: 'J',
  },
];

export default function EmployeesPage() {
  const [selectedEmployee, setSelectedEmployee] = useState(null);

  if (selectedEmployee) {
    return (
      <div className="w-full h-full min-h-screen bg-[#f4f6fa]">
        <ChatPage user={selectedEmployee} onBack={() => setSelectedEmployee(null)} />
      </div>
    );
  }

  return (
    <div className="w-full flex justify-center bg-[#f4f6fa] min-h-screen">
      <div className="w-full max-w-[1400px] px-8">
        <div className="relative flex items-center mb-6 bg-white p-4 rounded-lg shadow-md w-full" style={{margin: '32px 0 24px 0'}}>
          <div className="w-12 h-12 flex items-center justify-center bg-[#f4f5f7] rounded-lg mr-3">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="16.615" viewBox="0 0 18 16.615" className="w-6 h-6">
              <path id="employee-icon" d="M40.615,26.769H37.154v-.692A2.077,2.077,0,0,0,35.077,24H30.923a2.077,2.077,0,0,0-2.077,2.077v.692H25.385A1.385,1.385,0,0,0,24,28.154V39.231a1.385,1.385,0,0,0,1.385,1.385H40.615A1.385,1.385,0,0,0,42,39.231V28.154A1.385,1.385,0,0,0,40.615,26.769ZM30.231,28.154h5.538V39.231H30.231Zm0-2.077a.692.692,0,0,1,.692-.692h4.154a.692.692,0,0,1,.692.692v.692H30.231Z" transform="translate(-24 -24)" fill="#273E91" />
            </svg>
          </div>
          <div>
            <h1 className="text-gray-900 text-2xl font-bold" style={{ fontSize: 18, fontWeight: 600 }}>Procurement Team</h1>
            <p className="text-xs text-[#5f6b85]">Choose a specialist to start requirement capture and RFP drafting.</p>
          </div>
          <div className="absolute right-0 top-0 h-full w-1/3" style={{ backgroundSize: 'cover', backgroundPosition: 'right center' }}></div>
        </div>
        <div className="w-full grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-x-8 gap-y-10">
          {employees.map((emp) => (
            <EmployeeCard
              key={emp.name}
              {...emp}
              onMessageClick={() => setSelectedEmployee(emp)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
