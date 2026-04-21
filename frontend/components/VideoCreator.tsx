'use client';
import { useState, useEffect } from 'react';
import axios from 'axios';
import { API_BASE_URL, API_HOST } from '@/lib/api';

const resolveUrl = (u: string) => {
  if (!u) return '';
  if (u.startsWith('http://') || u.startsWith('https://')) return u;
  return `${API_HOST}${u.startsWith('/') ? '' : '/'}${u}`;
};

export default function VideoCreator() {
  const [topTab, setTopTab] = useState<'single' | 'long'>('single');
  const [mode, setMode] = useState<'text' | 'image'>('text');
  const [prompt, setPrompt] = useState('');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [resolution, setResolution] = useState('720p');
  const [duration, setDuration] = useState('8s');
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
          const url = data.download_url || (data.video_filename ? `/api/v1/video/download/${data.video_filename}` : '');
          if (url) setResultUrl(resolveUrl(url));
          reloadMyVideos();
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

  // My Videos
  const [myVideos, setMyVideos] = useState<any[]>([]);
  const [playingId, setPlayingId] = useState<string | null>(null);

  const reloadMyVideos = async () => {
    try {
      const res = await axios.get(`${API_BASE_URL}/jobs/my?job_type=veo_video&limit=30`);
      setMyVideos((res.data?.data?.jobs || []).filter((j: any) => j.status === 'completed' && j.result_url));
    } catch {}
  };
  useEffect(() => { reloadMyVideos(); }, []);

  // Enforce Veo 3.1 rule: 1080p/4k require 8s duration
  useEffect(() => {
    if ((resolution === '1080p' || resolution === '4k') && duration !== '8s') {
      setDuration('8s');
    }
  }, [resolution]);

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
      {/* Top-level tabs: Single vs Long */}
      <div className="card" style={{ padding: '6px', display: 'flex', gap: '4px', borderRadius: '14px' }}>
        {[
          { id: 'single', label: 'Single Video (4-8s)' },
          { id: 'long', label: 'Long Video (up to 148s)' },
        ].map(t => (
          <button key={t.id} type="button" onClick={() => setTopTab(t.id as any)}
            style={{
              flex: 1, padding: '10px 16px', borderRadius: '10px', border: 'none',
              fontSize: '14px', fontWeight: topTab === t.id ? 600 : 400, cursor: 'pointer',
              background: topTab === t.id ? '#0071e3' : 'transparent',
              color: topTab === t.id ? '#fff' : 'rgba(255,255,255,0.6)',
              transition: 'all 0.2s',
            }}
          >{t.label}</button>
        ))}
      </div>

      {topTab === 'long' && <LongVideoPanel />}
      {topTab === 'single' && (
      <>
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
                  <option value="1080p">1080p (8s only)</option>
                  <option value="4k">4K (8s only)</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>Duration</label>
                <select value={duration} onChange={e => setDuration(e.target.value)}
                  disabled={resolution === '1080p' || resolution === '4k'}
                  style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const, opacity: (resolution === '1080p' || resolution === '4k') ? 0.6 : 1 }}>
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

      {/* My Videos */}
      {myVideos.length > 0 && (
        <div className="card" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <label style={{ ...labelStyle, fontSize: '15px', marginBottom: 0 }}>My Videos</label>
            <button type="button" onClick={reloadMyVideos}
              style={{ padding: '6px 12px', borderRadius: '8px', border: 'none', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', fontSize: '12px', cursor: 'pointer' }}>
              Refresh
            </button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
            {myVideos.map((j: any) => {
              const videoUrl = resolveUrl(j.result_url || '');
              const thumbName = j.result_data?.thumb_filename;
              const thumbUrl = thumbName ? resolveUrl(`/api/v1/video/thumb/${thumbName}`) : '';
              const isPlaying = playingId === j.id;
              const isPortrait = j.input_data?.aspect_ratio === '9:16';
              const aspect = isPortrait ? '9/16' : '16/9';
              return (
                <div key={j.id} className="card" style={{ padding: '10px' }}>
                  <div style={{
                    position: 'relative', width: '100%', aspectRatio: aspect,
                    background: '#000', borderRadius: '8px', marginBottom: '8px',
                    overflow: 'hidden', cursor: isPlaying ? 'default' : 'pointer',
                  }}
                  onClick={() => !isPlaying && videoUrl && setPlayingId(j.id)}>
                    {isPlaying && videoUrl ? (
                      <video src={videoUrl} controls autoPlay playsInline
                        style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }} />
                    ) : thumbUrl ? (
                      <>
                        <img src={thumbUrl} alt=""
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
                        <div style={{
                          position: 'absolute', inset: 0, display: 'flex',
                          alignItems: 'center', justifyContent: 'center',
                          background: 'rgba(0,0,0,0.25)',
                        }}>
                          <div style={{
                            width: '44px', height: '44px', borderRadius: '50%',
                            background: 'rgba(255,255,255,0.95)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                          }}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="#000"><path d="M8 5v14l11-7z"/></svg>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div style={{
                        width: '100%', height: '100%', display: 'flex',
                        alignItems: 'center', justifyContent: 'center',
                        background: 'linear-gradient(135deg, #0071e3 0%, #2997ff 100%)',
                      }}>
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="rgba(255,255,255,0.9)"><path d="M8 5v14l11-7z"/></svg>
                      </div>
                    )}
                  </div>
                  <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)', margin: '0 0 8px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {j.input_data?.prompt || 'Veo video'}
                  </p>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    {!isPlaying && (
                      <button type="button" onClick={() => setPlayingId(j.id)}
                        style={{ flex: 1, padding: '6px', borderRadius: '6px', border: 'none', background: '#0071e3', color: '#fff', fontSize: '11px', fontWeight: 500, cursor: 'pointer' }}>
                        Play
                      </button>
                    )}
                    <a href={videoUrl} download target="_blank" rel="noopener noreferrer"
                      style={{ flex: 1, textAlign: 'center', padding: '6px', borderRadius: '6px', background: 'rgba(255,255,255,0.08)', color: '#2997ff', fontSize: '11px', textDecoration: 'none', fontWeight: 500 }}>
                      Download
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      </>
      )}
    </div>
  );
}


// ---------- Long Video Panel ----------
function LongVideoPanel() {
  const [script, setScript] = useState('');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [targetSegments, setTargetSegments] = useState(5);
  const [autoStitch, setAutoStitch] = useState(false);
  const [budget, setBudget] = useState(3.5);
  const [showAdvisory, setShowAdvisory] = useState(true);

  const [jobId, setJobId] = useState<string | null>(null);
  const [snap, setSnap] = useState<any>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);

  const inputStyle = { width: '100%', padding: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', outline: 'none' };
  const labelStyle = { fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase' as const, letterSpacing: '0.5px', marginBottom: '8px', display: 'block' };

  const estSec = 8 + (targetSegments - 1) * 7;
  const estCost = 0.40 + (targetSegments - 1) * 0.35;

  const handleStart = async () => {
    setError('');
    setStarting(true);
    setSnap(null);
    try {
      const res = await axios.post(`${API_BASE_URL}/video/long/create`, {
        script,
        aspect_ratio: aspectRatio,
        target_segments: targetSegments,
        auto_stitch: autoStitch,
        budget_usd: budget,
      });
      if (!res.data.success) throw new Error(res.data.message);
      setJobId(res.data.data.job_id);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to start long video');
    } finally {
      setStarting(false);
    }
  };

  // Poll status every 10s. Stops polling when job reaches a terminal state.
  useEffect(() => {
    if (!jobId) return;
    let cancelledFlag = false;
    let iv: ReturnType<typeof setInterval> | null = null;
    const tick = async () => {
      try {
        const res = await axios.get(`${API_BASE_URL}/video/long/status/${jobId}`);
        if (cancelledFlag) return;
        const data = res.data.data;
        setSnap(data);
        // Stop polling on terminal states
        if (data.status === 'completed' || data.status === 'cancelled' || data.status === 'failed') {
          if (iv) { clearInterval(iv); iv = null; }
        }
      } catch (e) {}
    };
    tick();
    iv = setInterval(tick, 10000);
    return () => { cancelledFlag = true; if (iv) clearInterval(iv); };
  }, [jobId]);

  const allDone = snap && snap.segments?.every((s: any) => s.status === 'completed' || s.status === 'failed' || s.status === 'skipped_budget' || s.status === 'cancelled');
  const isTerminal = snap && (snap.status === 'completed' || snap.status === 'cancelled' || snap.status === 'failed');

  const handleCancel = async () => {
    if (!jobId) return;
    if (!window.confirm('Cancel this long-video job? Segments already generated will be kept.')) return;
    try {
      const res = await axios.post(`${API_BASE_URL}/video/long/cancel/${jobId}`);
      setSnap(res.data.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Cancel failed');
    }
  };

  const handleStitchNow = async () => {
    if (!jobId) return;
    try {
      const res = await axios.post(`${API_BASE_URL}/video/long/stitch/${jobId}`);
      if (res.data.success) {
        // trigger a status refresh
        const s = await axios.get(`${API_BASE_URL}/video/long/status/${jobId}`);
        setSnap(s.data.data);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Stitch failed');
    }
  };

  const handleReset = () => {
    setJobId(null); setSnap(null); setError('');
  };

  return (
    <div className="space-y-5">
      {!jobId && (
        <>
          <div className="card" style={{ padding: '16px', background: 'rgba(0,113,227,0.08)', border: '1px solid rgba(0,113,227,0.25)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: showAdvisory ? '10px' : '0' }}>
              <p style={{ fontSize: '13px', fontWeight: 600, color: '#2997ff', margin: 0 }}>Tips for best results</p>
              <button type="button" onClick={() => setShowAdvisory(!showAdvisory)}
                style={{ background: 'none', border: 'none', color: '#2997ff', fontSize: '12px', cursor: 'pointer' }}>
                {showAdvisory ? 'Hide' : 'Show'}
              </button>
            </div>
            {showAdvisory && (
              <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.8)', lineHeight: 1.6 }}>
                <p style={{ margin: '0 0 8px 0' }}>
                  Describe <strong>one scene per line</strong> — each line becomes ~7 seconds of video.
                  Keep the subject & setting consistent across lines for smooth continuity.
                </p>
                <p style={{ margin: '0 0 8px 0' }}>
                  Include camera motion ("slow push in", "pan left") and lighting ("golden hour") for richer output.
                </p>
                <p style={{ margin: '0 0 8px 0' }}>
                  <strong>Any format works</strong> — timestamps, (8s) durations, numbered scenes, bullets, paragraphs. Parser handles it.
                </p>
                <pre style={{
                  background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: '8px',
                  fontSize: '12px', margin: '8px 0 0 0', whiteSpace: 'pre-wrap',
                  color: 'rgba(255,255,255,0.7)',
                }}>
{`Example:
Sunrise over a quiet coastal town, slow drone pullback.
Continuing pullback, revealing a fisherman walking to his boat.
Close-up on the fisherman's hands untying the rope.`}
                </pre>
              </div>
            )}
          </div>

          <div className="card" style={{ padding: '24px' }}>
            <label style={labelStyle}>Script</label>
            <textarea value={script} onChange={e => setScript(e.target.value)}
              placeholder="Paste your script in any format..."
              rows={10}
              style={{ ...inputStyle, resize: 'vertical' as const, fontFamily: 'ui-monospace, monospace' }} />

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '16px' }}>
              <div>
                <label style={labelStyle}>Aspect Ratio</label>
                <select value={aspectRatio} onChange={e => setAspectRatio(e.target.value)}
                  style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
                  <option value="16:9">16:9 (Landscape)</option>
                  <option value="9:16">9:16 (Portrait)</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>Budget (USD)</label>
                <select value={budget} onChange={e => setBudget(parseFloat(e.target.value))}
                  style={{ ...inputStyle, cursor: 'pointer', appearance: 'none' as const }}>
                  <option value="2.0">$2.00 (~5 clips)</option>
                  <option value="3.5">$3.50 (~10 clips)</option>
                  <option value="5.0">$5.00 (~14 clips)</option>
                  <option value="7.5">$7.50 (~21 clips, max)</option>
                </select>
              </div>
            </div>

            <div style={{ marginTop: '16px' }}>
              <label style={labelStyle}>Target Segments: {targetSegments} (~{estSec}s, est. ${estCost.toFixed(2)})</label>
              <input type="range" min={1} max={21} value={targetSegments}
                onChange={e => setTargetSegments(parseInt(e.target.value))}
                style={{ width: '100%', accentColor: '#0071e3' }} />
              <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginTop: '4px' }}>
                1 base clip (8s) + {targetSegments - 1} extensions (×7s each). Extension max = 20.
              </p>
            </div>

            <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <input type="checkbox" id="auto-stitch" checked={autoStitch}
                onChange={e => setAutoStitch(e.target.checked)}
                style={{ accentColor: '#0071e3', width: '18px', height: '18px' }} />
              <label htmlFor="auto-stitch" style={{ fontSize: '14px', color: '#e8e8ed', cursor: 'pointer' }}>
                Auto-stitch into one MP4 when done
              </label>
            </div>

            {error && (
              <div style={{ marginTop: '16px', padding: '12px', background: 'rgba(255,59,48,0.1)', borderLeft: '3px solid #ff3b30', borderRadius: '8px' }}>
                <p style={{ fontSize: '13px', color: '#ff6b6b', margin: 0 }}>{error}</p>
              </div>
            )}

            <button type="button" onClick={handleStart} disabled={starting || !script.trim()}
              style={{
                marginTop: '20px', width: '100%', padding: '14px', borderRadius: '10px', border: 'none',
                fontSize: '16px', fontWeight: 500, cursor: 'pointer',
                background: '#0071e3', color: '#fff',
                opacity: (starting || !script.trim()) ? 0.5 : 1,
              }}>
              {starting ? 'Starting...' : `Generate Long Video (~${estSec}s)`}
            </button>
          </div>
        </>
      )}

      {jobId && snap && (
        <div className="card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', gap: '12px' }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <p style={{ fontSize: '15px', fontWeight: 600, color: '#fff', margin: 0 }}>
                {snap.completed_count}/{snap.segment_count} segments ready
                {snap.status === 'cancelled' && <span style={{ color: '#ff6b6b', fontSize: '13px', marginLeft: '8px' }}>· Cancelled</span>}
                {snap.status === 'completed' && <span style={{ color: '#30d158', fontSize: '13px', marginLeft: '8px' }}>· Done</span>}
              </p>
              <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)', margin: '4px 0 0 0' }}>
                Cost so far: ${(snap.cost_so_far || 0).toFixed(2)}
                {snap.skipped_budget_count > 0 && ` · ${snap.skipped_budget_count} skipped (budget)`}
                {snap.failed_count > 0 && ` · ${snap.failed_count} failed`}
                {snap.cancelled_count > 0 && ` · ${snap.cancelled_count} cancelled`}
              </p>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              {!isTerminal && (
                <button type="button" onClick={handleCancel}
                  style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid rgba(255,69,58,0.4)', background: 'rgba(255,69,58,0.12)', color: '#ff6b6b', fontSize: '13px', cursor: 'pointer' }}>
                  Cancel
                </button>
              )}
              <button type="button" onClick={handleReset}
                style={{ padding: '8px 14px', borderRadius: '8px', border: 'none', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', fontSize: '13px', cursor: 'pointer' }}>
                New
              </button>
            </div>
          </div>

          {/* Progress bar */}
          <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', marginBottom: '20px', overflow: 'hidden' }}>
            <div style={{
              height: '100%', background: 'linear-gradient(90deg, #0071e3, #2997ff)',
              width: `${(snap.completed_count / snap.segment_count) * 100}%`,
              transition: 'width 0.5s ease',
            }} />
          </div>

          {/* Segments grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '12px' }}>
            {snap.segments.map((s: any) => {
              const statusColor = s.status === 'completed' ? '#30d158'
                : s.status === 'generating' ? '#ffd60a'
                : s.status === 'failed' ? '#ff6b6b'
                : s.status === 'cancelled' ? '#ff6b6b'
                : s.status === 'skipped_budget' ? '#8e8e93'
                : 'rgba(255,255,255,0.3)';
              const url = s.download_url ? resolveUrl(s.download_url) : '';
              return (
                <div key={s.index} className="card" style={{ padding: '10px' }}>
                  <div style={{
                    position: 'relative', width: '100%', aspectRatio: '16/9',
                    background: '#000', borderRadius: '6px', marginBottom: '8px',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {s.status === 'completed' && url ? (
                      <video src={url} controls playsInline
                        style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }} />
                    ) : (
                      <div style={{ textAlign: 'center' }}>
                        <div style={{
                          width: '28px', height: '28px', borderRadius: '50%',
                          border: '2px solid rgba(255,255,255,0.15)', borderTopColor: statusColor,
                          margin: '0 auto 6px',
                          animation: s.status === 'generating' ? 'spin 1s linear infinite' : 'none',
                        }} />
                        <p style={{ fontSize: '11px', color: statusColor, margin: 0, textTransform: 'uppercase' }}>
                          {s.status}
                        </p>
                      </div>
                    )}
                  </div>
                  <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)', margin: '0 0 6px 0', lineHeight: 1.4, height: '32px', overflow: 'hidden' }}>
                    #{s.index + 1} · {s.prompt.substring(0, 60)}
                  </p>
                  {s.status === 'completed' && url && (
                    <a href={url} download target="_blank" rel="noopener noreferrer"
                      style={{ display: 'block', textAlign: 'center', padding: '6px', borderRadius: '6px', background: 'rgba(255,255,255,0.08)', color: '#2997ff', fontSize: '11px', textDecoration: 'none' }}>
                      Download
                    </a>
                  )}
                  {s.error && (
                    <p style={{ fontSize: '10px', color: '#ff6b6b', margin: '4px 0 0 0' }}>{s.error.substring(0, 80)}</p>
                  )}
                </div>
              );
            })}
          </div>

          {/* Stitched output */}
          {snap.stitched_url && (
            <div style={{ marginTop: '24px', padding: '16px', background: 'rgba(48,209,88,0.08)', border: '1px solid rgba(48,209,88,0.25)', borderRadius: '10px' }}>
              <p style={{ fontSize: '13px', fontWeight: 600, color: '#30d158', margin: '0 0 10px 0' }}>Stitched Final Video</p>
              <video src={resolveUrl(snap.stitched_url)} controls
                style={{ width: '100%', borderRadius: '8px', background: '#000', marginBottom: '10px' }} />
              <a href={resolveUrl(snap.stitched_url)} download
                style={{ display: 'block', textAlign: 'center', padding: '10px', borderRadius: '8px', background: 'rgba(48,209,88,0.15)', color: '#30d158', fontSize: '14px', textDecoration: 'none', fontWeight: 500 }}>
                Download Full MP4
              </a>
            </div>
          )}

          {/* Manual stitch button when auto-stitch was off */}
          {allDone && !snap.auto_stitch && !snap.stitched_url && snap.completed_count >= 2 && (
            <button type="button" onClick={handleStitchNow}
              style={{
                marginTop: '16px', width: '100%', padding: '12px', borderRadius: '10px',
                fontSize: '14px', fontWeight: 500, cursor: 'pointer',
                background: 'rgba(0,113,227,0.2)', color: '#2997ff', border: '1px solid rgba(0,113,227,0.4)',
              }}>
              Stitch {snap.completed_count} segments into one MP4
            </button>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
