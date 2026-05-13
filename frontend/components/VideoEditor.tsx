'use client';

import { useState, useRef } from 'react';
import { editVideo, API_HOST } from '../lib/api';

const labelStyle: React.CSSProperties = {
  fontSize: '12px', fontWeight: 600, color: 'rgba(255,255,255,0.45)',
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '6px', display: 'block',
};

const COLOR_GRADES = ['none', 'cinematic', 'warm', 'cool', 'vivid'];
const CAPTION_STYLES = [
  { id: 'subtitle', label: 'Subtitle (bottom, white)' },
  { id: 'bold_center', label: 'Bold center (large)' },
];
const MUSIC_MOODS = ['', 'motivational', 'upbeat', 'energetic', 'calm', 'dramatic', 'corporate', 'inspiring'];
const ASPECTS = ['16:9', '9:16', '1:1'];

export default function VideoEditor() {
  const [file, setFile] = useState<File | null>(null);
  const [colorGrade, setColorGrade] = useState('none');
  const [captionText, setCaptionText] = useState('');
  const [captionStyle, setCaptionStyle] = useState('subtitle');
  const [musicMood, setMusicMood] = useState('');
  const [selectedAspects, setSelectedAspects] = useState<string[]>(['16:9', '9:16', '1:1']);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState<Record<string, string> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function toggleAspect(a: string) {
    setSelectedAspects(prev =>
      prev.includes(a) ? prev.filter(x => x !== a) : [...prev, a]
    );
  }

  async function handleSubmit() {
    if (!file) return;
    setProcessing(true); setError(''); setResults(null);
    try {
      const fd = new FormData();
      fd.append('video', file);
      fd.append('color_grade', colorGrade);
      fd.append('caption_text', captionText);
      fd.append('caption_style', captionStyle);
      fd.append('music_mood', musicMood);
      fd.append('output_aspects', selectedAspects.join(','));
      const r = await editVideo(fd);
      if (r.success && r.data?.urls) {
        const resolved: Record<string, string> = {};
        for (const [aspect, url] of Object.entries(r.data.urls as Record<string, string>)) {
          resolved[aspect] = url.startsWith('http') ? url : `${API_HOST}${url}`;
        }
        setResults(resolved);
      } else {
        setError(r.message || 'Edit failed');
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || 'Failed');
    } finally {
      setProcessing(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* Upload + Options */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', alignItems: 'start' }}>

        {/* Upload */}
        <div className="card" style={{ padding: '20px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#e8e8ed', marginBottom: '16px' }}>Upload Video</h3>

          <div
            onClick={() => fileRef.current?.click()}
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              minHeight: '160px', borderRadius: '12px', cursor: 'pointer',
              background: 'rgba(255,255,255,0.04)', border: '1px dashed rgba(255,255,255,0.2)',
              transition: 'all 0.15s',
            }}
          >
            <input ref={fileRef} type="file" accept="video/*" style={{ display: 'none' }}
              onChange={e => { setFile(e.target.files?.[0] || null); setResults(null); }} />
            {file ? (
              <div style={{ textAlign: 'center', padding: '16px' }}>
                <p style={{ fontSize: '14px', color: '#30d158', marginBottom: '4px' }}>{file.name}</p>
                <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.35)' }}>
                  {(file.size / 1024 / 1024).toFixed(1)} MB · click to replace
                </p>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '24px' }}>
                <p style={{ fontSize: '32px', marginBottom: '8px', color: 'rgba(255,255,255,0.3)' }}>+</p>
                <p style={{ fontSize: '14px', color: 'rgba(255,255,255,0.45)' }}>Click to upload video</p>
                <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.25)', marginTop: '4px' }}>MP4, MOV, AVI (max 500MB)</p>
              </div>
            )}
          </div>

          {file && (
            <video
              src={URL.createObjectURL(file)}
              controls
              style={{ width: '100%', borderRadius: '8px', marginTop: '12px', maxHeight: '200px', objectFit: 'contain', background: '#000' }}
            />
          )}
        </div>

        {/* Options */}
        <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#e8e8ed', margin: 0 }}>Edit Options</h3>

          {/* Color grade */}
          <div>
            <label style={labelStyle}>Color grade</label>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {COLOR_GRADES.map(g => (
                <button key={g} onClick={() => setColorGrade(g)}
                  style={{
                    padding: '6px 12px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                    fontSize: '13px', transition: 'all 0.15s',
                    background: colorGrade === g ? '#0071e3' : 'rgba(255,255,255,0.08)',
                    color: colorGrade === g ? '#fff' : 'rgba(255,255,255,0.6)',
                  }}>
                  {g === 'none' ? 'None' : g.charAt(0).toUpperCase() + g.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Captions */}
          <div>
            <label style={labelStyle}>Caption text (burns into video)</label>
            <textarea
              value={captionText}
              onChange={e => setCaptionText(e.target.value)}
              placeholder="Leave blank for no captions. Enter text to burn in — e.g. 'Limited time offer: save 40%'"
              rows={3}
              className="input"
              style={{ fontSize: '14px', padding: '9px 12px', resize: 'vertical' }}
            />
            {captionText.trim() && (
              <div style={{ display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' }}>
                {CAPTION_STYLES.map(s => (
                  <button key={s.id} onClick={() => setCaptionStyle(s.id)}
                    style={{
                      padding: '5px 10px', borderRadius: '6px', border: 'none', cursor: 'pointer',
                      fontSize: '12px', transition: 'all 0.15s',
                      background: captionStyle === s.id ? '#0071e3' : 'rgba(255,255,255,0.08)',
                      color: captionStyle === s.id ? '#fff' : 'rgba(255,255,255,0.5)',
                    }}>{s.label}</button>
                ))}
              </div>
            )}
          </div>

          {/* Music */}
          <div>
            <label style={labelStyle}>Background music (Pixabay CC0)</label>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {MUSIC_MOODS.map(m => (
                <button key={m || 'none'} onClick={() => setMusicMood(m)}
                  style={{
                    padding: '6px 12px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                    fontSize: '13px', transition: 'all 0.15s',
                    background: musicMood === m ? '#0071e3' : 'rgba(255,255,255,0.08)',
                    color: musicMood === m ? '#fff' : 'rgba(255,255,255,0.6)',
                  }}>
                  {m === '' ? 'No music' : m.charAt(0).toUpperCase() + m.slice(1)}
                </button>
              ))}
            </div>
            {musicMood && <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.3)', marginTop: '6px' }}>Auto-mixed at -14 LUFS</p>}
          </div>

          {/* Output aspects */}
          <div>
            <label style={labelStyle}>Export formats</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              {ASPECTS.map(a => (
                <button key={a} onClick={() => toggleAspect(a)}
                  style={{
                    padding: '7px 14px', borderRadius: '8px', border: `1px solid ${selectedAspects.includes(a) ? '#0071e3' : 'rgba(255,255,255,0.12)'}`,
                    cursor: 'pointer', fontSize: '13px', fontWeight: 500, transition: 'all 0.15s',
                    background: selectedAspects.includes(a) ? 'rgba(0,113,227,0.15)' : 'rgba(255,255,255,0.04)',
                    color: selectedAspects.includes(a) ? '#2997ff' : 'rgba(255,255,255,0.5)',
                  }}>
                  {a}
                </button>
              ))}
            </div>
          </div>

          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={!file || processing || selectedAspects.length === 0}
            style={{ fontSize: '15px', marginTop: '4px' }}
          >
            {processing ? 'Processing...' : 'Apply Edits'}
          </button>

          {processing && (
            <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', marginTop: '4px' }}>
              Running ffmpeg pipeline — this can take 30–120 seconds depending on video length
            </p>
          )}

          {error && (
            <div style={{ background: 'rgba(255,69,58,0.1)', border: '1px solid rgba(255,69,58,0.3)', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#ff6961' }}>
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Results */}
      {results && Object.keys(results).length > 0 && (
        <div className="card" style={{ padding: '20px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#e8e8ed', marginBottom: '16px' }}>
            Edited Versions — ready to download
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
            {Object.entries(results).map(([aspect, url]) => (
              <div key={aspect} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '12px', overflow: 'hidden' }}>
                <div style={{
                  aspectRatio: aspect === '9:16' ? '9/16' : aspect === '1:1' ? '1/1' : '16/9',
                  maxHeight: aspect === '9:16' ? '320px' : '200px',
                  background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <video src={url} controls style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                </div>
                <div style={{ padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8ed' }}>{aspect}</span>
                  <a href={url} download style={{
                    padding: '6px 14px', borderRadius: '8px', background: '#0071e3', color: '#fff',
                    fontSize: '13px', textDecoration: 'none', fontWeight: 500,
                  }}>Download</a>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
