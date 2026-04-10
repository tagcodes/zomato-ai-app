import React from 'react';

interface BottomNavProps {
  activeTab: 'explore' | 'assistant' | 'orders' | 'profile';
}

export default function BottomNav({ activeTab }: BottomNavProps) {
  return (
    <nav className="nav-bar">
      <div className={`nav-item ${activeTab === 'explore' ? 'active' : ''}`}>
        <span style={{ fontSize: '24px' }}>🧭</span>
        <span>Explore</span>
      </div>
      <div className={`nav-item ${activeTab === 'assistant' ? 'active' : ''}`}>
        <span style={{ fontSize: '24px' }}>🤖</span>
        <span>AI Assistant</span>
      </div>
      <div className={`nav-item ${activeTab === 'orders' ? 'active' : ''}`}>
        <span style={{ fontSize: '24px' }}>📋</span>
        <span>Orders</span>
      </div>
      <div className={`nav-item ${activeTab === 'profile' ? 'active' : ''}`}>
        <span style={{ fontSize: '24px' }}>👤</span>
        <span>Profile</span>
      </div>
    </nav>
  );
}
