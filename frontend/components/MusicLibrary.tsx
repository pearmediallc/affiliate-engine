'use client';

import { useState, useRef } from 'react';
import { searchMusic } from '../lib/api';

const labelStyle: React.CSSProperties = {
  fontSize: '12px', fontWeight: 600, color: 'rgba(255,255,255,0.45)',
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '6px', display: 'block',
};

const MOODS = [
  'motivational', 'upbeat', 'energetic', 'calm', 'dramatic',
  'emotional', 'corporate', 'happy', 'inspiring', 'tense',
];

interface Track {
  id: string; title: string; duration: number;
  audio_url: string; preview_url: string; tags: string; genre: string; mood: string;
}

function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function MusicLibrary() {
  const [mood, setMood] = useState('motivational');
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function handleSearch() {
    setLoading(true); setError(''); setTracks([]);
    try {
      const r = await searchMusic(mood);
      setTracks(r.data?.tracks || []);
      if ((r.data?.tracks || []).length === 0) {
        setError('No tracks found for this mood. Try another.');
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Search failed — check PIXABAY_API_KEY is set');
    } finally {
      setLoading(false);
    }
  }

  function handlePlay(track: Track) {
    const src = track.preview_url || track.audio_url;
    if (!src) return;
    if (playingId === track.id) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    if (audioRef.current) {
      audioRef.current.pause();
    }
    const audio = new Audio(src);
    audio.play();
    audio.onended = () => setPlayingId(null);
    audioRef.current = audio;
    setPlayingId(track.id);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* Search controls */}
      <div className="card" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '16px', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: '280px' }}>
            <label style={labelStyle}>Mood / genre</label>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {MOODS.map(m => (
                <button key={m} onClick={() => setMood(m)}
                  style={{
                    padding: '6px 13px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                    fontSize: '13px', transition: 'all 0.15s',
                    background: mood === m ? '#0071e3' : 'rgba(255,255,255,0.08)',
                    color: mood === m ? '#fff' : 'rgba(255,255,255,0.6)',
                  }}>
                  {m.charAt(0).toUpperCase() + m.slice(1)}
                </button>
              ))}
            </div>
          </div>
          <button className="btn-primary" onClick={handleSearch} disabled={loading}
            style={{ fontSize: '14px', padding: '10px 20px', flexShrink: 0 }}>
            {loading ? 'Searching...' : 'Search Tracks'}
          </button>
        </div>

        <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.3)', marginTop: '12px' }}>
          Powered by Pixabay — all tracks are CC0 (free for commercial use, no attribution required).
          Requires PIXABAY_API_KEY in Render environment.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div style={{ background: 'rgba(255,69,58,0.1)', border: '1px solid rgba(255,69,58,0.3)', borderRadius: '10px', padding: '12px 16px', fontSize: '13px', color: '#ff6961' }}>
          {error}
        </div>
      )}

      {/* Results */}
      {tracks.length > 0 && (
        <div className="card" style={{ padding: '20px' }}>
          <p style={{ ...labelStyle, marginBottom: '14px' }}>{tracks.length} tracks found — {mood}</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {tracks.map(track => (
              <div key={track.id}
                style={{
                  display: 'flex', alignItems: 'center', gap: '14px',
                  padding: '12px 14px', borderRadius: '10px',
                  background: playingId === track.id ? 'rgba(0,113,227,0.1)' : 'rgba(255,255,255,0.04)',
                  border: `1px solid ${playingId === track.id ? 'rgba(0,113,227,0.3)' : 'rgba(255,255,255,0.06)'}`,
                  transition: 'all 0.15s',
                }}>
                {/* Play button */}
                <button
                  onClick={() => handlePlay(track)}
                  style={{
                    width: '38px', height: '38px', borderRadius: '50%', border: 'none', cursor: 'pointer',
                    background: playingId === track.id ? '#0071e3' : 'rgba(255,255,255,0.1)',
                    color: '#fff', fontSize: '14px', flexShrink: 0, transition: 'all 0.15s',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                  {playingId === track.id ? '■' : '▶'}
                </button>

                {/* Track info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: '14px', fontWeight: 500, color: '#e8e8ed', marginBottom: '3px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {track.title || `Track ${track.id}`}
                  </p>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>{formatDuration(track.duration)}</span>
                    <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.25)', background: 'rgba(255,255,255,0.07)', padding: '2px 7px', borderRadius: '999px' }}>{track.genre}</span>
                    <span style={{ fontSize: '11px', color: '#30d158', background: 'rgba(48,209,88,0.1)', padding: '2px 7px', borderRadius: '999px' }}>CC0</span>
                  </div>
                </div>

                {/* Download */}
                {(track.audio_url || track.preview_url) && (
                  <a
                    href={track.audio_url || track.preview_url}
                    download={`track-${track.id}.mp3`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      padding: '7px 14px', borderRadius: '8px', background: 'rgba(255,255,255,0.08)',
                      color: '#e8e8ed', fontSize: '12px', textDecoration: 'none',
                      border: '1px solid rgba(255,255,255,0.12)', whiteSpace: 'nowrap', flexShrink: 0,
                    }}>
                    Download MP3
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && tracks.length === 0 && !error && (
        <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
          <p style={{ fontSize: '14px', color: 'rgba(255,255,255,0.4)', marginBottom: '8px' }}>Select a mood and search for CC0 tracks</p>
          <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.25)' }}>Free for commercial use — no attribution required</p>
        </div>
      )}
    </div>
  );
}
