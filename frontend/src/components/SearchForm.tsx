'use client';

import React, { useState, useEffect } from 'react';
import { getLocations, getLocalities, RecommendRequest } from '@/lib/api';

interface SearchFormProps {
  onSearch: (req: RecommendRequest) => void;
  isLoading: boolean;
}

export default function SearchForm({ onSearch, isLoading }: SearchFormProps) {
  const [cities, setCities] = useState<string[]>([]);
  const [localities, setLocalities] = useState<string[]>([]);
  const [selectedCity, setSelectedCity] = useState('');
  const [selectedLocality, setSelectedLocality] = useState('');
  const [cuisine, setCuisine] = useState('');
  const [budgetTier, setBudgetTier] = useState<1 | 2 | 3>(2);
  const [minRating] = useState(3.5);

  useEffect(() => {
    getLocations().then(setCities).catch(console.error);
    // Default to first city if available
    getLocations().then(data => { if (data.length) setSelectedCity(data[0]); });
  }, []);

  useEffect(() => {
    if (selectedCity) {
      getLocalities(selectedCity).then(setLocalities).catch(console.error);
    }
  }, [selectedCity]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch({
      location: selectedLocality || selectedCity || 'Bangalore',
      cuisine: cuisine || 'Trending',
      min_rating: minRating,
      budget_max_inr: budgetTier === 1 ? 500 : budgetTier === 2 ? 1200 : 3000,
    });
  };

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--text-gray)', marginBottom: '12px' }}>Current Location</h3>
        <div className="card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '0' }}>
          <div style={{ width: '40px', height: '40px', background: '#FEF2F2', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--zomato-red)' }}>
            📍
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: '700', fontSize: '15px' }}>{selectedLocality || selectedCity || 'Searching...'}</div>
            <div style={{ fontSize: '12px', color: 'var(--text-gray)' }}>{selectedCity ? `${selectedCity}, India` : 'Set your location'}</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
           <select 
             value={selectedCity} 
             onChange={(e) => setSelectedCity(e.target.value)}
             style={{ flex: 1, minWidth: 0, fontSize: '12px', padding: '8px', borderRadius: '8px', border: '1px solid var(--border-light)' }}
           >
             {cities.map(c => <option key={c} value={c}>{c}</option>)}
           </select>
           {localities.length > 0 && (
             <select 
               value={selectedLocality} 
               onChange={(e) => setSelectedLocality(e.target.value)}
               style={{ flex: 1, minWidth: 0, fontSize: '12px', padding: '8px', borderRadius: '8px', border: '1px solid var(--border-light)' }}
             >
               <option value="">Any Locality</option>
               {localities.map(l => <option key={l} value={l}>{l}</option>)}
             </select>
           )}
        </div>
      </div>

      <div style={{ marginBottom: '30px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--text-gray)', marginBottom: '12px' }}>The Budget</h3>
        <div style={{ display: 'flex', gap: '12px' }}>
          {[
            { tier: 1, icon: '$', label: 'Value' },
            { tier: 2, icon: '$$', label: 'Mid-range' },
            { tier: 3, icon: '$$$', label: 'Splurge' }
          ].map((item) => (
            <div 
              key={item.tier}
              className={`budget-card ${budgetTier === item.tier ? 'active' : ''}`}
              onClick={() => setBudgetTier(item.tier as 1|2|3)}
            >
              <span className="icon">{item.icon}</span>
              <span className="label">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: '30px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--text-gray)', marginBottom: '12px' }}>What are you craving?</h3>
        <input 
          placeholder="e.g. Spicy Ramen, Healthy Brunch"
          value={cuisine}
          onChange={(e) => setCuisine(e.target.value)}
          style={{ padding: '16px', borderRadius: '16px' }}
        />
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px' }}>
           {['Italian', 'Japanese', 'Mexican', 'Healthy'].map(c => (
             <div 
               key={c} 
               onClick={() => setCuisine(c)}
               className="pill-ai" 
               style={{ background: cuisine === c ? 'var(--zomato-red)' : '#F0F0F0', color: cuisine === c ? 'white' : '#1C1C1C', cursor: 'pointer' }}
              >
               {c}
             </div>
           ))}
        </div>
      </div>

      <button className="zomato-btn" disabled={isLoading}>
        <span>✨</span> {isLoading ? 'Analyzing...' : 'Find my perfect table'}
      </button>
    </form>
  );
}
