'use client';
import { useState } from 'react';
import axios from 'axios';
import { API_BASE_URL, API_HOST } from '@/lib/api';

export default function TalkingHead() {
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [model, setModel] = useState('sadtalker');
  const [generating, setGenerating] = useState(false);
  const [status, setStatus] = useState('');
  const [resultUrl, setResultUrl] = useState('');
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    if (!imageFile || !audioFile) { setError('Upload both a portrait image and audio file'); return; }
    setGenerating(true); setError(''); setStatus('Uploading files...'); setResultUrl('');

    try {
      const formData = new FormData();
      formData.append('image', imageFile);
      formData.append('audio', audioFile);
      formData.append('model', model);

      const res = await axios.post(`${API_BASE_URL}/lip-sync/generate`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      if (!res.data.success) throw new Error(res.data.message);

      const predictionId = res.data.data.prediction_id;
      setStatus('Generating talking head video...');

      // Poll for completion
      const poll = async () => {
        for (let i = 0; i < 120; i++) {
          await new Promise(r => setTimeout(r, 5000));
          const statusRes = await axios.get(`${API_BASE_URL}/lip-sync/status/${predictionId}`);
          const data = statusRes.data.data;

          if (data.status === 'succeeded') {
            setStatus('Complete!');
            if (data.download_filename) {
              setResultUrl(`${API_HOST}/api/v1/lip-sync/download/${data.download_filename}`);
            } else if (data.video_url) {
              setResultUrl(data.video_url);
            }
            return;
          } else if (data.status === 'failed') {
            throw new Error(data.error || 'Generation failed');
          }
          setStatus(`Generating... (${data.status})`);
        }
        throw new Error('Timed out waiting for result');
      };

      await poll();
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const inputStyle = { width: '100%', padding: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', outline: 'none' };
  const labelStyle = { fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase' as const, letterSpacing: '0.5px', marginBottom: '8px', display: 'block' };

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      <div className="card" style={{ padding: '24px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          {/* Portrait upload */}
          <div>
            <label style={labelStyle}>Portrait Image</label>
            <div style={{ ...inputStyle, padding: '24px', textAlign: 'center', cursor: 'pointer', position: 'relative' }}
              onClick={() => document.getElementById('lip-img-input')?.click()}>
              {imageFile ? (
                <div>
                  <p style={{ color: '#30d158', fontSize: '14px' }}>{imageFile.name}</p>
                  <p style={{ color: 'rgba(255,255,255,0.3)', fontSize: '12px', marginTop: '4px' }}>{(imageFile.size / 1024 / 1024).toFixed(1)}MB</p>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '24px', marginBottom: '8px' }}>+</p>
                  <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '13px' }}>Drop portrait here</p>
                  <p style={{ color: 'rgba(255,255,255,0.25)', fontSize: '11px', marginTop: '4px' }}>PNG, JPG (max 10MB)</p>
                </div>
              )}
              <input id="lip-img-input" type="file" accept="image/*" style={{ display: 'none' }}
                onChange={e => setImageFile(e.target.files?.[0] || null)} />
            </div>
          </div>

          {/* Audio upload */}
          <div>
            <label style={labelStyle}>Audio File</label>
            <div style={{ ...inputStyle, padding: '24px', textAlign: 'center', cursor: 'pointer' }}
              onClick={() => document.getElementById('lip-audio-input')?.click()}>
              {audioFile ? (
                <div>
                  <p style={{ color: '#2997ff', fontSize: '14px' }}>{audioFile.name}</p>
                  <p style={{ color: 'rgba(255,255,255,0.3)', fontSize: '12px', marginTop: '4px' }}>{(audioFile.size / 1024 / 1024).toFixed(1)}MB</p>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '24px', marginBottom: '8px' }}>+</p>
                  <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '13px' }}>Drop audio here</p>
                  <p style={{ color: 'rgba(255,255,255,0.25)', fontSize: '11px', marginTop: '4px' }}>MP3, WAV (max 10MB)</p>
                </div>
              )}
              <input id="lip-audio-input" type="file" accept="audio/*,.mp3,.wav" style={{ display: 'none' }}
                onChange={e => setAudioFile(e.target.files?.[0] || null)} />
            </div>
          </div>
        </div>

        {/* Model selector */}
        <div style={{ marginTop: '16px' }}>
          <label style={labelStyle}>Model</label>
          <select value={model} onChange={e => setModel(e.target.value)}
            style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
            <option value="sadtalker">SadTalker (Recommended)</option>
          </select>
        </div>

        {/* Error */}
        {error && (
          <div style={{ marginTop: '16px', padding: '12px 16px', background: 'rgba(255,59,48,0.1)', borderLeft: '3px solid #ff3b30', borderRadius: '8px' }}>
            <p style={{ fontSize: '14px', color: '#ff6b6b', margin: 0 }}>{error}</p>
          </div>
        )}

        {/* Status */}
        {status && !error && (
          <div style={{ marginTop: '16px', padding: '12px 16px', background: 'rgba(0,113,227,0.1)', borderLeft: '3px solid #0071e3', borderRadius: '8px' }}>
            <p style={{ fontSize: '14px', color: '#2997ff', margin: 0 }}>{status}</p>
          </div>
        )}

        {/* Generate button */}
        <button onClick={handleGenerate} disabled={generating || !imageFile || !audioFile}
          style={{
            marginTop: '20px', width: '100%', padding: '14px', borderRadius: '10px', border: 'none',
            fontSize: '16px', fontWeight: 500, cursor: 'pointer',
            background: '#0071e3', color: '#fff',
            opacity: (generating || !imageFile || !audioFile) ? 0.5 : 1,
          }}>
          {generating ? 'Generating...' : 'Generate Talking Head Video'}
        </button>
      </div>

      {/* Result */}
      {resultUrl && (
        <div className="card" style={{ padding: '24px' }}>
          <label style={labelStyle}>Generated Video</label>
          <video controls style={{ width: '100%', borderRadius: '10px', background: '#000' }} src={resultUrl} />
          <a href={resultUrl} download style={{
            display: 'block', marginTop: '12px', padding: '12px', borderRadius: '10px',
            background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)',
            color: '#2997ff', textAlign: 'center', fontSize: '14px', textDecoration: 'none',
          }}>
            Download MP4
          </a>
        </div>
      )}
    </div>
  );
}
