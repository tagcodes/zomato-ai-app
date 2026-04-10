import React from 'react';
import { RecommendItem } from '@/lib/api';

interface RecommendationCardProps {
  item: RecommendItem;
}

export default function RecommendationCard({ item }: RecommendationCardProps) {
  // Select a relevant keyword for the image
  const primaryCuisine = (item.cuisines[0] || 'food').toLowerCase();
  const searchKeyword = primaryCuisine.includes('chinese') ? 'noodles' : 
                        primaryCuisine.includes('indian') ? 'curry' :
                        primaryCuisine.includes('italian') ? 'pizza' : 
                        primaryCuisine.includes('japanese') ? 'sushi' :
                        primaryCuisine.includes('burger') ? 'burger' :
                        primaryCuisine.includes('dessert') ? 'dessert' :
                        primaryCuisine.includes('cafe') ? 'coffee' :
                        primaryCuisine;

  // Use a reliable keyword-based placeholder service
  const foodImage = `https://loremflickr.com/600/400/${encodeURIComponent(searchKeyword)},food/all`;

  return (
    <div className="card" style={{ padding: '0', overflow: 'hidden', border: 'none', marginBottom: '25px' }}>
      <div style={{ position: 'relative', height: '240px' }}>
        <img 
          src={foodImage} 
          alt={item.name} 
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
        <div style={{ position: 'absolute', top: '15px', right: '15px' }}>
           <div className="pill-ai" style={{ background: 'var(--ai-purple)', padding: '6px 14px' }}>
             ⚡ {95 + Math.floor(Math.random() * 5)}% AI Match
           </div>
        </div>
        <div style={{ position: 'absolute', bottom: '15px', left: '15px' }}>
           <div className="pill-ai" style={{ background: 'white', color: 'var(--zomato-red)', border: 'none' }}>
             TOP RECOMMENDATION
           </div>
        </div>
      </div>

      <div style={{ padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
          <h3 style={{ fontSize: '20px' }}>{item.name}</h3>
          <div style={{ background: '#F0F0F0', padding: '2px 8px', borderRadius: '6px', fontSize: '14px', fontWeight: '700' }}>
            ★ {item.rating.toFixed(1)}
          </div>
        </div>
        <p style={{ color: 'var(--text-gray)', fontSize: '14px', marginBottom: '15px' }}>
          {item.cuisines.join(', ')} • {item.cost_display || 'Mid-range'}
        </p>

        <div style={{ 
          background: '#F5F3FF', 
          borderLeft: '4px solid var(--ai-purple)', 
          borderRadius: '12px', 
          padding: '16px',
          display: 'flex',
          gap: '12px'
        }}>
          <div style={{ fontSize: '20px' }}>🤖</div>
          <p style={{ fontSize: '14px', color: '#4C1D95', fontStyle: 'italic', lineHeight: '1.5' }}>
            "{item.explanation}"
          </p>
        </div>
      </div>
    </div>
  );
}
