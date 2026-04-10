'use client';

import React, { useState } from 'react';
import Hero from '@/components/Hero';
import SearchForm from '@/components/SearchForm';
import RecommendationCard from '@/components/RecommendationCard';
import BottomNav from '@/components/BottomNav';
import { getRecommendations, RecommendRequest, RecommendResponse } from '@/lib/api';

export default function Home() {
  const [recommendations, setRecommendations] = useState<RecommendResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'home' | 'results'>('home');
  const [viewMode, setViewMode] = useState<'mobile' | 'website'>('mobile');

  const handleSearch = async (req: RecommendRequest) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getRecommendations(req);
      setRecommendations(data);
      setView('results');
    } catch (err: any) {
      console.error(err);
      setError(err?.message || 'Something went wrong.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleBack = () => setView('home');

  const toggleViewMode = () => {
    setViewMode(prev => prev === 'mobile' ? 'website' : 'mobile');
  };

  return (
    <div className={`app-container view-${viewMode}`}>
      <button 
        className="view-toggle" 
        onClick={toggleViewMode}
        title={`Switch to ${viewMode === 'mobile' ? 'Website' : 'Mobile'} View`}
      >
        {viewMode === 'mobile' ? '🖥️ View as Website' : '📱 View as App'}
      </button>
      <div style={{ flex: 1 }}>
        <Hero view={view} onBack={handleBack} />
        
        {view === 'home' ? (
          <div className="content-padding">
            <h2 className="section-title" style={{ margin: '20px 0' }}>Fine-tune your cravings</h2>
            <p style={{ color: 'var(--text-gray)', fontSize: '14px', marginBottom: '20px' }}>
              Tell Zomato AI what you're looking for, and we'll handle the discovery.
            </p>
            <SearchForm onSearch={handleSearch} isLoading={isLoading} />
          </div>
        ) : (
          <div className="content-padding" style={{ paddingBottom: '40px' }}>
            {error && (
              <div style={{ padding: '15px', borderRadius: '12px', background: '#fee2e2', color: '#b91c1c', marginBottom: '20px' }}>
                {error}
              </div>
            )}
            
            {recommendations && (
              <div>
                 <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '15px' }}>
                  <span style={{ fontSize: '20px' }}>✨</span>
                  <p style={{ fontSize: '15px', fontWeight: '500', color: 'var(--text-gray)' }}>
                    "I'm looking for {recommendations.summary.toLowerCase()}"
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
                   <div className="pill-ai" style={{ background: 'var(--zomato-red)' }}>AI Top Picks</div>
                   <div className="pill-ai" style={{ background: '#F0F0F0', color: '#1C1C1C' }}>Distance</div>
                   <div className="pill-ai" style={{ background: '#F0F0F0', color: '#1C1C1C' }}>Rating 4.5+</div>
                </div>

                <div className="results-grid">
                  {recommendations.items.map(item => (
                    <RecommendationCard key={item.id} item={item} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {viewMode === 'mobile' && (
        <BottomNav activeTab={view === 'home' ? 'assistant' : 'assistant'} />
      )}
    </div>
  );
}
