import React from 'react';

interface HeroProps {
  view: 'home' | 'results';
  onBack?: () => void;
}

export default function Hero({ view, onBack }: HeroProps) {
  return (
    <header style={{ 
      padding: '20px', 
      display: 'flex', 
      alignItems: 'center', 
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      background: 'white',
      zIndex: 10
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {view === 'results' && onBack && (
          <button onClick={onBack} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '20px' }}>
            ←
          </button>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ 
            width: '32px', 
            height: '32px', 
            borderRadius: '50%', 
            background: '#eee',
            overflow: 'hidden'
          }}>
            <img 
              src="https://images.unsplash.com/photo-1599566150163-29194dcaad36?ixlib=rb-1.2.1&auto=format&fit=crop&w=64&q=80" 
              alt="Avatar" 
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          </div>
          <span style={{ fontWeight: '800', fontSize: '18px' }}>Zomato AI</span>
        </div>
      </div>
      <div style={{ color: 'var(--zomato-red)', fontSize: '20px' }}>
        ✨
      </div>
    </header>
  );
}
