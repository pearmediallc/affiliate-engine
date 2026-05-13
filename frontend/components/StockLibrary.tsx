'use client';

import { useState, useRef } from 'react';
import { searchStock } from '../lib/api';

const labelStyle: React.CSSProperties = {
  fontSize: '12px', fontWeight: 600, color: 'rgba(255,255,255,0.45)',
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '6px', display: 'block',
};

const ORIENTATIONS = [
  { id: 'portrait', label: '9:16 Portrait' },
  { id: 'landscape', label: '16:9 Landscape' },
  { id: 'square', label: '1:1 Square' },
];

const QUICK_QUERIES = [
  'lifestyle', 'product closeup', 'nature', 'city urban', 'gym workout',
  'office work', 'family home', 'food cooking', 'technology', 'driving car',
];

interface Clip {
  id: string; duration: number; width: number; height: number;
  download_url: string; thumbnail: string; photographer: string; license: string;
}

function formatDuration(sec: number): string {
  return `${sec}s`;
}

export default function StockLibrary() {
  const [query, setQuery] = useState('');
  const [orientation, setOrientation] = useState('portrait');
  const [clips, setClips] = useState<Clip[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [playingId, setPlayingId] = useState<string | null>(null);
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});

  async function handleSearch(q?: string) {
    const searchQ = q || query;
    if (!searchQ.trim()) return;
    setLoading(true); setError(''); setClips([]);
    setQuery(searchQ);
    try {
      const r = await searchStock(searchQ, orientation);
      setClips(r.data?.clips || []);
      if ((r.data?.clips || []).length === 0) {
        setError('No clips found. Try a different query or orientation.');
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Search failed — check PEXELS_API_KEY is set');
    } finally {
      setLoading(false);
    }
  }

  function handleHover(id: string, enter: boolean) {
    const vid = videoRefs.current[id];
    if (!vid) return;
    if (enter) {
      vid.play().catch(() => {});
      setPlayingId(id);
    } else {
      vid.pause();
      vid.currentTime = 0;
      setPlayingId(null);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* Search controls */}
      <div className="card" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: '16px' }}>
          <div style={{ flex: 1, minWidth: '220px' }}>
            <label style={labelStyle}>Search query</label>
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="e.g. lifestyle, product closeup, city urban..."
              className="input"
              style={{ fontSize: '14px', padding: '9px 12px' }}
            />
          </div>
          <div>
            <label style={labelStyle}>Orientation</label>
            <div style={{ display: 'flex', gap: '6px' }}>
              {ORIENTATIONS.map(o => (
                <button key={o.id} onClick={() => setOrientation(o.id)}
                  style={{
                    padding: '8px 12px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                    fontSize: '12px', transition: 'all 0.15s',
                    background: orientation === o.id ? '#0071e3' : 'rgba(255,255,255,0.08)',
                    color: orientation === o.id ? '#fff' : 'rgba(255,255,255,0.6)',
                  }}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <button className="btn-primary" onClick={() => handleSearch()}
            disabled={loading || !query.trim()}
            style={{ fontSize: '14px', padding: '10px 20px', flexShrink: 0 }}>
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>

        {/* Quick queries */}
        <div>
          <label style={{ ...labelStyle, marginBottom: '8px' }}>Quick searches</label>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {QUICK_QUERIES.map(q => (
              <button key={q} onClick={() => handleSearch(q)}
                style={{
                  padding: '5px 11px', borderRadius: '999px', border: '1px solid rgba(255,255,255,0.12)',
                  background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.55)',
                  fontSize: '12px', cursor: 'pointer', transition: 'all 0.15s',
                }}>
                {q}
              </button>
            ))}
          </div>
        </div>

        <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.25)', marginTop: '12px' }}>
          Powered by Pexels — free for commercial use. Requires PEXELS_API_KEY in Render environment.
          Hover a clip to preview.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div style={{ background: 'rgba(255,69,58,0.1)', border: '1px solid rgba(255,69,58,0.3)', borderRadius: '10px', padding: '12px 16px', fontSize: '13px', color: '#ff6961' }}>
          {error}
        </div>
      )}

      {/* Grid */}
      {clips.length > 0 && (
        <div className="card" style={{ padding: '20px' }}>
          <p style={{ ...labelStyle, marginBottom: '16px' }}>{clips.length} clips found — "{query}"</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
            {clips.map(clip => (
              <div key={clip.id}
                style={{ borderRadius: '12px', overflow: 'hidden', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}
                onMouseEnter={() => handleHover(clip.id, true)}
                onMouseLeave={() => handleHover(clip.id, false)}
              >
                {/* Video preview */}
                <div style={{
                  position: 'relative', background: '#000',
                  aspectRatio: orientation === '9:16' || orientation === 'portrait' ? '9/16' : orientation === 'square' ? '1/1' : '16/9',
                  maxHeight: orientation === 'portrait' ? '280px' : '160px',
                }}>
                  {clip.thumbnail && (
                    <img src={clip.thumbnail} alt=""
                      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
                  )}
                  <video
                    ref={el => { videoRefs.current[clip.id] = el; }}
                    src={clip.download_url}
                    muted loop playsInline preload="none"
                    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', opacity: playingId === clip.id ? 1 : 0, transition: 'opacity 0.2s' }}
                  />
                  <div style={{
                    position: 'absolute', bottom: '6px', left: '6px',
                    background: 'rgba(0,0,0,0.6)', borderRadius: '4px',
                    padding: '2px 6px', fontSize: '11px', color: '#e8e8ed',
                  }}>{formatDuration(clip.duration)}</div>
                  {playingId !== clip.id && (
                    <div style={{
                      position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <div style={{ width: '36px', height: '36px', borderRadius: '50%', background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', color: '#fff' }}>▶</div>
                    </div>
                  )}
                </div>

                {/* Meta + download */}
                <div style={{ padding: '10px 12px' }}>
                  <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginBottom: '6px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {clip.photographer || 'Pexels'} · {clip.width}×{clip.height}
                  </p>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                    <span style={{ fontSize: '11px', color: '#30d158', background: 'rgba(48,209,88,0.1)', padding: '2px 7px', borderRadius: '999px', flexShrink: 0 }}>Free</span>
                    <a
                      href={clip.download_url}
                      download={`pexels-${clip.id}.mp4`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        flex: 1, textAlign: 'center', padding: '5px 8px', borderRadius: '7px',
                        background: '#0071e3', color: '#fff', fontSize: '12px',
                        textDecoration: 'none', fontWeight: 500,
                      }}>
                      Download
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && clips.length === 0 && !error && (
        <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
          <p style={{ fontSize: '14px', color: 'rgba(255,255,255,0.4)', marginBottom: '8px' }}>Search for free B-roll footage</p>
          <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.25)' }}>Pexels library — free commercial license, hover to preview</p>
        </div>
      )}
    </div>
  );
}
