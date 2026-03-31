import React from 'react';

import messageIcon from '../../Assets/message-icon.svg';

export default function EmployeeCard({ name, title, img, bg, onMessageClick }) {
  return (
    <div className="bg-white rounded-xl shadow-lg overflow-hidden text-center p-0 border border-[#e8e8e8]">

      <div className="relative w-full h-56 bg-cover bg-center flex justify-center items-center rounded-t-lg" style={{ backgroundImage: `url('${bg || "/assets/bg1--k_-nFql.jpg"}')` }}>
        <img
          src={img}
          alt={name}
          className="w-40 h-40 object-cover"
          style={{ width: '16rem', height: '14rem' }}
        />
      </div>
      <div className="p-6" style={{ textAlign: 'justify' }}>
        <div className="text-[#19058c] text-lg font-semibold">{name}</div>
        <div className="text-gray-500 mb-4" style={{ marginBottom: '24px' }}>{title}</div>
        <div className="flex justify-center">
          <button
            className="flex items-center space-x-2 px-4 py-2 rounded-lg transition-colors"
            style={{ backgroundColor: '#eef1f5', color: '#343434', cursor: 'pointer' }}
            onClick={onMessageClick}
          >
            <img src={messageIcon} alt="Open chat icon" className="h-5 w-5" />
            <span>Start RFP Chat</span>
          </button>
        </div>
      </div>
    </div>
  );
}
