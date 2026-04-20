'use client';
import { useState } from 'react';
import axios from 'axios';
import { API_BASE_URL, API_HOST } from '@/lib/api';

export default function VideoCreator() {
  const [mode, setMode] = useState<'text' | 'image'>('text');
  const [prompt, setPrompt] = useState('');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [resolution, setResolution] = useState('1080p');
  const [duration, setDuration] = useState('6s');
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [generating, setGenerating] = useState(false);
  const [status, setStatus] = useState('');
  const [resultUrl, setResultUrl] = useState('');
  const [error, setError] = useState('');

  // Enhancement state
  const [colorGrade, setColorGrade] = useState('cinematic');
  const [platform, setPlatform] = useState('tiktok');
  const [textOverlay, setTextOverlay] = useState('');
  const [textPosition, setTextPosition] = useState('center');
  const [enhancing, setEnhancing] = useState(false);
  const [enhancedUrl, setEnhancedUrl] = useState('');

  const handleGenerate = async () => {
    if (!prompt.trim()) { setError('Enter a prompt'); return; }
    if (mode === 'image' && !imageFile) { setError('Upload an image for image-to-video mode'); return; }
    setGenerating(true); setError(''); setStatus('Submitting...'); setResultUrl(''); setEnhancedUrl('');

    try {
      let operationName: string;

      if (mode === 'text') {
        const res = await axios.post(`${API_BASE_URL}/video/generate`, {
          prompt,
          aspect_ratio: aspectRatio,
          resolution,
          duration,
        });
        if (!res.data.success) throw new Error(res.data.message);
        operationName = res.data.data.operation_name;
      } else {
        const formData = new FormData();
        formData.append('image', imageFile!);
        formData.append('prompt', prompt);
        formData.append('aspect_ratio', aspectRatio);
        const res = await axios.post(`${API_BASE_URL}/video/generate-from-image`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        if (!res.data.success) throw new Error(res.data.message);
        operationName = res.data.data.operation_name;
      }

      setStatus('Generating video with Veo 3.1...');

      // Poll for completion
      for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 10000));
        const statusRes = await axios.get(`${API_BASE_URL}/video/status/${operationName}`);
        const data = statusRes.data.data;

        if (data.done) {
          setStatus('Complete!');
          if (data.download_url) {
            setResultUrl(data.download_url);
          } else if (data.download_filename) {
            setResultUrl(`${API_HOST}/api/v1/video/download/${data.download_filename}`);
          }
          return;
        }
        if (data.error) {
          throw new Error(data.error);
        }
        setStatus(`Generating... (${Math.round((i + 1) * 10)}s elapsed)`);
      }
      throw new Error('Timed out waiting for result');
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const handleEnhance = async () => {
    if (!resultUrl) return;
    setEnhancing(true); setError(''); setEnhancedUrl('');

    try {
      // Fetch the video as a blob to upload
      const videoBlob = await fetch(resultUrl).then(r => r.blob());
      const formData = new FormData();
      formData.append('video', videoBlob, 'video.mp4');
      formData.append('color_grade', colorGrade);
      formData.append('platform', platform);
      if (textOverlay.trim()) {
        formData.append('text_overlay', textOverlay);
        formData.append('text_position', textPosition);
      }

      const res = await axios.post(`${API_BASE_URL}/video-enhance/enhance`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      if (res.data.success && res.data.data?.download_url) {
        setEnhancedUrl(res.data.data.download_url);
      } else if (res.data.data?.download_filename) {
        setEnhancedUrl(`${API_HOST}/api/v1/video-enhance/download/${res.data.data.download_filename}`);
      } else {
        throw new Error(res.data.message || 'Enhancement failed');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Enhancement failed');
    } finally {
      setEnhancing(false);
    }
  };

  const inputStyle = { width: '100%', padding: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', outline: 'none' };
  const labelStyle = { fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase' as const, letterSpacing: '0.5px', marginBottom: '8px', display: 'block' };
  const tabStyle = (active: boolean) => ({
    flex: 1, padding: '10px', borderRadius: '8px', border: 'none', cursor: 'pointer',
    fontSize: '14px', fontWeight: 500,
    background: active ? 'rgba(0,113,227,0.3)' : 'transparent',
    color: active ? '#2997ff' : 'rgba(255,255,255,0.5)',
  });

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      <div className="card" style={{ padding: '24px' }}>
        {/* Mode tabs */}
        <div style={{ display: 'flex', gap: '4px', padding: '4px', background: 'rgba(255,255,255,0.04)', borderRadius: '10px', marginBottom: '20px' }}>
          <button style={tabStyle(mode === 'text')} onClick={() => setMode('text')}>Text to Video</button>
          <button style={tabStyle(mode === 'image')} onClick={() => setMode('image')}>Image to Video</button>
        </div>

        {/* Image upload (image mode only) */}
        {mode === 'image' && (
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Source Image</label>
            <div style={{ ...inputStyle, padding: '24px', textAlign: 'center', cursor: 'pointer' }}
              onClick={() => document.getElementById('vc-img-input')?.click()}>
              {imageFile ? (
                <div>
                  <p style={{ color: '#30d158', fontSize: '14px' }}>{imageFile.name}</p>
                  <p style={{ color: 'rgba(255,255,255,0.3)', fontSize: '12px', marginTop: '4px' }}>{(imageFile.size / 1024 / 1024).toFixed(1)}MB</p>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '24px', marginBottom: '8px' }}>+</p>
                  <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '13px' }}>Upload source image</p>
                  <p style={{ color: 'rgba(255,255,255,0.25)', fontSize: '11px', marginTop: '4px' }}>PNG, JPG (max 10MB)</p>
                </div>
              )}
              <input id="vc-img-input" type="file" accept="image/*" style={{ display: 'none' }}
                onChange={e => setImageFile(e.target.files?.[0] || null)} />
            </div>
          </div>
        )}

        {/* Prompt */}
        <div style={{ marginBottom: '16px' }}>
          <label style={labelStyle}>Prompt</label>
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)}
            placeholder="Describe the video you want to create..."
            rows={3}
            style={{ ...inputStyle, resize: 'vertical' as const }} />
        </div>

        {/* Settings row */}
        <div style={{ display: 'grid', gridTemplateColumns: mode === 'text' ? '1fr 1fr 1fr' : '1fr', gap: '12px', marginBottom: '16px' }}>
          <div>
            <label style={labelStyle}>Aspect Ratio</label>
            <select value={aspectRatio} onChange={e => setAspectRatio(e.target.value)}
              style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
              <option value="16:9">16:9 (Landscape)</option>
              <option value="9:16">9:16 (Portrait)</option>
            </select>
          </div>
          {mode === 'text' && (
            <>
              <div>
                <label style={labelStyle}>Resolution</label>
                <select value={resolution} onChange={e => setResolution(e.target.value)}
                  style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
                  <option value="720p">720p</option>
                  <option value="1080p">1080p</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>Duration</label>
                <select value={duration} onChange={e => setDuration(e.target.value)}
                  style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
                  <option value="4s">4 seconds</option>
                  <option value="6s">6 seconds</option>
                  <option value="8s">8 seconds</option>
                </select>
              </div>
            </>
          )}
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
        <button onClick={handleGenerate} disabled={generating || !prompt.trim() || (mode === 'image' && !imageFile)}
          style={{
            marginTop: '20px', width: '100%', padding: '14px', borderRadius: '10px', border: 'none',
            fontSize: '16px', fontWeight: 500, cursor: 'pointer',
            background: '#0071e3', color: '#fff',
            opacity: (generating || !prompt.trim()) ? 0.5 : 1,
          }}>
          {generating ? 'Generating...' : 'Generate Video'}
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

      {/* Enhancement section */}
      {resultUrl && (
        <div className="card" style={{ padding: '24px' }}>
          <label style={{ ...labelStyle, fontSize: '15px', marginBottom: '16px' }}>Enhance Video</label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>Color Grade</label>
              <select value={colorGrade} onChange={e => setColorGrade(e.target.value)}
                style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
                <option value="warm">Warm</option>
                <option value="cool">Cool</option>
                <option value="cinematic">Cinematic</option>
                <option value="vintage">Vintage</option>
                <option value="vivid">Vivid</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>Platform</label>
              <select value={platform} onChange={e => setPlatform(e.target.value)}
                style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
                <option value="tiktok">TikTok</option>
                <option value="reels">Instagram Reels</option>
                <option value="youtube">YouTube</option>
                <option value="instagram">Instagram</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '12px', marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>Text Overlay</label>
              <input type="text" value={textOverlay} onChange={e => setTextOverlay(e.target.value)}
                placeholder="Optional overlay text..."
                style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Position</label>
              <select value={textPosition} onChange={e => setTextPosition(e.target.value)}
                style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
                <option value="top">Top</option>
                <option value="center">Center</option>
                <option value="bottom">Bottom</option>
              </select>
            </div>
          </div>

          <button onClick={handleEnhance} disabled={enhancing}
            style={{
              width: '100%', padding: '14px', borderRadius: '10px',
              fontSize: '16px', fontWeight: 500, cursor: 'pointer',
              background: 'rgba(255,255,255,0.1)', color: '#fff',
              border: '1px solid rgba(255,255,255,0.15)',
              opacity: enhancing ? 0.5 : 1,
            }}>
            {enhancing ? 'Enhancing...' : 'Enhance Video'}
          </button>

          {/* Enhanced result */}
          {enhancedUrl && (
            <div style={{ marginTop: '16px' }}>
              <label style={labelStyle}>Enhanced Video</label>
              <video controls style={{ width: '100%', borderRadius: '10px', background: '#000' }} src={enhancedUrl} />
              <a href={enhancedUrl} download style={{
                display: 'block', marginTop: '12px', padding: '12px', borderRadius: '10px',
                background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)',
                color: '#2997ff', textAlign: 'center', fontSize: '14px', textDecoration: 'none',
              }}>
                Download Enhanced MP4
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
