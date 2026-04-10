const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface RecommendRequest {
  location: string;
  cuisine: string;
  min_rating: number;
  extras?: string;
  budget_max_inr?: number;
}

export interface RecommendItem {
  id: string;
  name: string;
  cuisines: string[];
  rating: number;
  estimated_cost?: string;
  cost_display?: string;
  explanation: string;
  rank: number;
}

export interface RecommendResponse {
  summary: string;
  items: RecommendItem[];
  meta: {
    shortlist_size: number;
    model: string;
    reason?: string;
  };
}

export async function getLocations(): Promise<string[]> {
  const res = await fetch(`${BASE_URL}/api/v1/locations`);
  if (!res.ok) throw new Error('Failed to fetch locations');
  const data = await res.json();
  return data.locations || [];
}

export async function getLocalities(city?: string): Promise<string[]> {
  const url = city 
    ? `${BASE_URL}/api/v1/localities?city=${encodeURIComponent(city)}`
    : `${BASE_URL}/api/v1/localities`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('Failed to fetch localities');
  const data = await res.json();
  return data.localities || [];
}

export async function getRecommendations(req: RecommendRequest): Promise<RecommendResponse> {
  const res = await fetch(`${BASE_URL}/api/v1/recommend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API Error: ${text}`);
  }
  return res.json();
}
