'use client';
import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '@/lib/api';

interface Script {
  id: string;
  content: string;
  duration?: string;
}

interface Avatar {
  avatar_id: string;
  avatar_name: string;
  preview_image_url?: string;
  preview_video_url?: string;
}

interface Video {
  video_id: string;
  video_name?: string;
  avatar_name?: string;
  duration?: number;
  created_at?: string;
  thumbnail_url?: string;
  video_url?: string;
  status?: string;
}

function ScriptsTab({ onUseScript }: { onUseScript: (script: string) => void }) {
  const [mode, setMode] = useState<'custom' | 'product'>('custom');
  const [prompt, setPrompt] = useState('');
  const [count, setCount] = useState(3);
  const [duration, setDuration] = useState('30s');
  const [productName, setProductName] = useState('');
  const [productDescription, setProductDescription] = useState('');
  const [tone, setTone] = useState('Friendly');
  const [style, setStyle] = useState('Educational');
  const [pov, setPov] = useState('First Person');
  const [language, setLanguage] = useState('English');
  const [industry, setIndustry] = useState('General');
  const [isGenerating, setIsGenerating] = useState(false);
  const [scripts, setScripts] = useState<Script[]>([]);
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    setIsGenerating(true);
    setError('');
    setScripts([]);
    try {
      const payload = mode === 'custom'
        ? { mode: 'custom', prompt, count, duration }
        : { mode: 'product', product_name: productName, product_description: productDescription, tone, style, pov, language, industry, count, duration };

      const res = await axios.post(`${API_BASE_URL}/tiktok/scripts/generate`, payload);
      const taskId = res.data.task_id || res.data.data?.task_id;

      if (taskId) {
        const poll = setInterval(async () => {
          try {
            const statusRes = await axios.get(`${API_BASE_URL}/tiktok/scripts/status?task_id=${taskId}`);
            const status = statusRes.data.status || statusRes.data.data?.status;
            if (status === 'complete' || status === 'completed') {
              clearInterval(poll);
              setScripts(statusRes.data.scripts || statusRes.data.data?.scripts || []);
              setIsGenerating(false);
            } else if (status === 'failed' || status === 'error') {
              clearInterval(poll);
              setError('Script generation failed. Please try again.');
              setIsGenerating(false);
            }
          } catch {
            clearInterval(poll);
            setError('Failed to check status.');
            setIsGenerating(false);
          }
        }, 3000);
      } else if (res.data.scripts || res.data.data?.scripts) {
        setScripts(res.data.scripts || res.data.data?.scripts);
        setIsGenerating(false);
      } else {
        setError('Unexpected response format.');
        setIsGenerating(false);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to generate scripts');
      setIsGenerating(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Mode Toggle */}
      <div className="card" style={{ padding: '6px', display: 'flex', gap: '4px', borderRadius: '14px' }}>
        {[
          { id: 'custom', label: 'Custom Prompt' },
          { id: 'product', label: 'Product Info' },
        ].map(m => (
          <button key={m.id} type="button" onClick={() => setMode(m.id as any)}
            style={{
              flex: 1, padding: '10px 16px', borderRadius: '10px', border: 'none',
              fontSize: '14px', fontWeight: mode === m.id ? 600 : 400, cursor: 'pointer',
              background: mode === m.id ? '#0071e3' : 'transparent',
              color: mode === m.id ? '#fff' : 'rgba(255,255,255,0.6)',
              transition: 'all 0.2s',
            }}
          >{m.label}</button>
        ))}
      </div>

      <div className="card" style={{ padding: '20px' }}>
        {mode === 'custom' ? (
          <div className="space-y-4">
            <div>
              <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Prompt</p>
              <textarea value={prompt} onChange={e => setPrompt(e.target.value)}
                placeholder="Describe the UGC video script you want..."
                style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', height: '100px', resize: 'none', outline: 'none' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 140px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Count</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="range" min="1" max="8" value={count} onChange={e => setCount(parseInt(e.target.value))}
                    style={{ flex: 1, accentColor: '#0071e3' }} />
                  <span style={{ fontSize: '14px', fontWeight: 600, color: '#2997ff', minWidth: '20px', textAlign: 'center' }}>{count}</span>
                </div>
              </div>
              <div style={{ flex: '1 1 140px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Duration</p>
                <select value={duration} onChange={e => setDuration(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}>
                  <option value="15s">15 seconds</option>
                  <option value="30s">30 seconds</option>
                </select>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Product Name</p>
              <input type="text" value={productName} onChange={e => setProductName(e.target.value)}
                placeholder="Enter product name..."
                style={{ width: '100%', padding: '10px 14px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', outline: 'none' }}
              />
            </div>
            <div>
              <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Product Description</p>
              <textarea value={productDescription} onChange={e => setProductDescription(e.target.value)}
                placeholder="Describe what the product does..."
                style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', height: '80px', resize: 'none', outline: 'none' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 140px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Tone</p>
                <select value={tone} onChange={e => setTone(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}>
                  <option value="Friendly">Friendly</option>
                  <option value="Professional">Professional</option>
                  <option value="Casual">Casual</option>
                  <option value="Enthusiastic">Enthusiastic</option>
                </select>
              </div>
              <div style={{ flex: '1 1 140px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Style</p>
                <select value={style} onChange={e => setStyle(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}>
                  <option value="Educational">Educational</option>
                  <option value="Testimonial">Testimonial</option>
                  <option value="Storytelling">Storytelling</option>
                  <option value="Demo">Demo</option>
                </select>
              </div>
              <div style={{ flex: '1 1 140px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>POV</p>
                <select value={pov} onChange={e => setPov(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}>
                  <option value="First Person">First Person</option>
                  <option value="Second Person">Second Person</option>
                  <option value="Third Person">Third Person</option>
                </select>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 140px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Language</p>
                <select value={language} onChange={e => setLanguage(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}>
                  <option value="English">English</option>
                  <option value="Spanish">Spanish</option>
                  <option value="French">French</option>
                  <option value="German">German</option>
                </select>
              </div>
              <div style={{ flex: '1 1 140px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Industry</p>
                <select value={industry} onChange={e => setIndustry(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}>
                  <option value="General">General</option>
                  <option value="Health">Health</option>
                  <option value="Finance">Finance</option>
                  <option value="Technology">Technology</option>
                  <option value="Beauty">Beauty</option>
                  <option value="Fitness">Fitness</option>
                </select>
              </div>
              <div style={{ flex: '1 1 100px' }}>
                <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Count</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="range" min="1" max="8" value={count} onChange={e => setCount(parseInt(e.target.value))}
                    style={{ flex: 1, accentColor: '#0071e3' }} />
                  <span style={{ fontSize: '14px', fontWeight: 600, color: '#2997ff', minWidth: '20px', textAlign: 'center' }}>{count}</span>
                </div>
              </div>
            </div>
            <div style={{ flex: '1 1 140px' }}>
              <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Duration</p>
              <select value={duration} onChange={e => setDuration(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}>
                <option value="15s">15 seconds</option>
                <option value="30s">30 seconds</option>
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Generate Button */}
      <button type="button" onClick={handleGenerate} disabled={isGenerating || (mode === 'custom' && !prompt.trim()) || (mode === 'product' && !productName.trim())}
        style={{
          width: '100%', padding: '16px', borderRadius: '12px', border: 'none',
          fontSize: '16px', fontWeight: 500, cursor: 'pointer',
          background: '#0071e3', color: '#fff',
          opacity: (isGenerating || (mode === 'custom' && !prompt.trim()) || (mode === 'product' && !productName.trim())) ? 0.5 : 1,
          transition: 'all 0.2s',
        }}>
        {isGenerating ? 'Generating Scripts...' : 'Generate Scripts'}
      </button>

      {error && <p style={{ fontSize: '13px', color: '#ff6b6b', textAlign: 'center' }}>{error}</p>}

      {/* Generated Scripts */}
      {scripts.length > 0 && (
        <div className="space-y-3">
          <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Generated Scripts</p>
          {scripts.map((script, i) => (
            <div key={script.id || i} className="card" style={{ padding: '16px' }}>
              <p style={{ fontSize: '14px', color: '#e8e8ed', lineHeight: 1.6, whiteSpace: 'pre-wrap', marginBottom: '12px' }}>
                {script.content}
              </p>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="button" onClick={() => onUseScript(script.content)}
                  style={{ flex: 1, padding: '8px 16px', borderRadius: '8px', border: 'none', background: '#0071e3', color: '#fff', fontSize: '13px', fontWeight: 500, cursor: 'pointer' }}>
                  Use for Video
                </button>
                <button type="button" onClick={() => navigator.clipboard.writeText(script.content)}
                  style={{ padding: '8px 16px', borderRadius: '8px', border: 'none', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', fontSize: '13px', fontWeight: 500, cursor: 'pointer' }}>
                  Copy
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateVideoTab({ initialScript }: { initialScript: string }) {
  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [selectedAvatar, setSelectedAvatar] = useState<string>('');
  const [script, setScript] = useState(initialScript);
  const [videoName, setVideoName] = useState('');
  const [isLoadingAvatars, setIsLoadingAvatars] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [videoResult, setVideoResult] = useState<{ video_url?: string } | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setScript(initialScript);
  }, [initialScript]);

  const loadAvatars = useCallback(async () => {
    setIsLoadingAvatars(true);
    setError('');
    try {
      const res = await axios.get(`${API_BASE_URL}/tiktok/avatars`);
      const data = res.data?.data || res.data;
      console.log('Avatar API response:', JSON.stringify(data).substring(0, 500));
      const rawList = data?.digital_avatar_list || data?.list || data?.avatars || [];
      // Normalize field names — TikTok API uses various field names for images
      const avatarList = rawList.map((a: any) => ({
        avatar_id: a.avatar_id || a.id || '',
        avatar_name: a.avatar_name || a.name || a.display_name || `Avatar ${a.avatar_id || a.id || ''}`,
        preview_image_url: (() => {
          const imgUrl = a.avatar_thumbnail || a.preview_image_url || a.image_url || a.cover_image_url || a.thumbnail_url || '';
          return imgUrl ? `${API_BASE_URL}/tiktok/proxy-image?url=${encodeURIComponent(imgUrl)}` : '';
        })(),
        preview_video_url: a.avatar_preview_url || a.preview_video_url || a.demo_video_url || a.video_url || '',
      }));
      console.log('Parsed avatars sample:', JSON.stringify(avatarList[0]).substring(0, 300));
      setAvatars(avatarList);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to load avatars');
      console.error('Avatar load error:', err);
    } finally {
      setIsLoadingAvatars(false);
    }
  }, []);

  useEffect(() => {
    loadAvatars();
  }, [loadAvatars]);

  const handleCreate = async () => {
    if (!selectedAvatar || !script.trim()) return;
    setIsCreating(true);
    setError('');
    setVideoResult(null);
    try {
      const res = await axios.post(`${API_BASE_URL}/tiktok/videos/create`, {
        avatar_id: selectedAvatar,
        script: script,
        video_name: videoName || undefined,
      });
      const taskIds = res.data.task_ids || res.data.data?.task_ids || [res.data.task_id || res.data.data?.task_id];

      if (taskIds.length > 0 && taskIds[0]) {
        const poll = setInterval(async () => {
          try {
            const statusRes = await axios.get(`${API_BASE_URL}/tiktok/videos/status?task_ids=${JSON.stringify(taskIds)}`);
            const status = statusRes.data.status || statusRes.data.data?.status;
            if (status === 'complete' || status === 'completed') {
              clearInterval(poll);
              setVideoResult(statusRes.data.video || statusRes.data.data?.video || statusRes.data);
              setIsCreating(false);
            } else if (status === 'failed' || status === 'error') {
              clearInterval(poll);
              setError('Video creation failed.');
              setIsCreating(false);
            }
          } catch {
            clearInterval(poll);
            setError('Failed to check video status.');
            setIsCreating(false);
          }
        }, 5000);
      } else {
        setVideoResult(res.data.video || res.data.data?.video || res.data);
        setIsCreating(false);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to create video');
      setIsCreating(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Step 1: Avatars */}
      <div className="card" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>Step 1: Select Avatar</p>
          <button type="button" onClick={loadAvatars} disabled={isLoadingAvatars}
            style={{ padding: '8px 16px', borderRadius: '8px', border: 'none', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', fontSize: '13px', cursor: 'pointer' }}>
            {isLoadingAvatars ? 'Loading...' : avatars.length ? 'Refresh' : 'Load Avatars'}
          </button>
        </div>
        {avatars.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: '12px' }}>
            {avatars.filter(avatar => avatar.avatar_id).map(avatar => (
              <div key={avatar.avatar_id} onClick={() => setSelectedAvatar(avatar.avatar_id)}
                style={{
                  padding: '8px', borderRadius: '12px', cursor: 'pointer', textAlign: 'center',
                  background: 'rgba(255,255,255,0.04)',
                  border: selectedAvatar === avatar.avatar_id ? '2px solid #0071e3' : '2px solid rgba(255,255,255,0.08)',
                  transition: 'all 0.2s',
                }}>
                {avatar.preview_image_url ? (
                  <img src={avatar.preview_image_url} alt={avatar.avatar_name}
                    style={{ width: '100%', aspectRatio: '1', objectFit: 'cover', borderRadius: '8px', marginBottom: '6px' }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; (e.target as HTMLImageElement).nextElementSibling && ((e.target as HTMLImageElement).nextElementSibling as HTMLElement).style.setProperty('display', 'flex'); }} />
                ) : null}
                {/* Fallback avatar with initial */}
                <div style={{
                  width: '100%', aspectRatio: '1', borderRadius: '8px', marginBottom: '6px',
                  display: avatar.preview_image_url ? 'none' : 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  background: `hsl(${(avatar.avatar_name || '').charCodeAt(0) * 7 % 360}, 50%, 35%)`,
                  fontSize: '28px', fontWeight: 700, color: 'rgba(255,255,255,0.8)',
                }}>
                  {(avatar.avatar_name || '?')[0].toUpperCase()}
                </div>
                <p style={{ fontSize: '11px', color: '#e8e8ed', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{avatar.avatar_name}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Step 2: Script */}
      <div className="card" style={{ padding: '20px' }}>
        <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Step 2: Script</p>
        <textarea value={script} onChange={e => setScript(e.target.value)}
          placeholder="Enter or paste your script here..."
          style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', height: '120px', resize: 'none', outline: 'none' }}
        />
        <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', marginTop: '6px', textAlign: 'right' }}>{script.length}/2000</p>
        <div style={{ marginTop: '12px' }}>
          <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Video Name (Optional)</p>
          <input type="text" value={videoName} onChange={e => setVideoName(e.target.value)}
            placeholder="My UGC Video"
            style={{ width: '100%', padding: '10px 14px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', outline: 'none' }}
          />
        </div>
      </div>

      {/* Create Button */}
      <button type="button" onClick={handleCreate} disabled={isCreating || !selectedAvatar || !script.trim()}
        style={{
          width: '100%', padding: '16px', borderRadius: '12px', border: 'none',
          fontSize: '16px', fontWeight: 500, cursor: 'pointer',
          background: '#0071e3', color: '#fff',
          opacity: (isCreating || !selectedAvatar || !script.trim()) ? 0.5 : 1,
          transition: 'all 0.2s',
        }}>
        {isCreating ? 'Creating Video...' : 'Create Speaking Video'}
      </button>

      {error && <p style={{ fontSize: '13px', color: '#ff6b6b', textAlign: 'center' }}>{error}</p>}

      {/* Video Result */}
      {videoResult && videoResult.video_url && (
        <div className="card" style={{ padding: '20px' }}>
          <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '12px' }}>Result</p>
          <video src={videoResult.video_url} controls
            style={{ width: '100%', borderRadius: '10px', marginBottom: '12px' }} />
          <a href={videoResult.video_url} download
            style={{ display: 'block', textAlign: 'center', padding: '10px', borderRadius: '8px', background: 'rgba(255,255,255,0.08)', color: '#2997ff', fontSize: '14px', textDecoration: 'none' }}>
            Download Video
          </a>
        </div>
      )}
    </div>
  );
}

function VideosTab() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    loadVideos();
  }, []);

  const loadVideos = async () => {
    setIsLoading(true);
    setError('');
    try {
      const res = await axios.get(`${API_BASE_URL}/tiktok/videos/list`);
      setVideos(res.data.videos || res.data.data?.videos || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to load videos');
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="card" style={{ padding: '40px', textAlign: 'center' }}>
        <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: '14px' }}>Loading videos...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card" style={{ padding: '20px', textAlign: 'center' }}>
        <p style={{ color: '#ff6b6b', fontSize: '14px' }}>{error}</p>
        <button type="button" onClick={loadVideos}
          style={{ marginTop: '12px', padding: '8px 16px', borderRadius: '8px', border: 'none', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', fontSize: '13px', cursor: 'pointer' }}>
          Retry
        </button>
      </div>
    );
  }

  if (videos.length === 0) {
    return (
      <div className="card" style={{ padding: '40px', textAlign: 'center' }}>
        <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: '14px' }}>No videos yet. Create your first UGC video!</p>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '16px' }}>
      {videos.map((video, i) => (
        <div key={video.video_id || i} className="card" style={{ padding: '12px', overflow: 'hidden' }}>
          {video.thumbnail_url ? (
            <img src={video.thumbnail_url} alt={video.video_name || 'Video'}
              style={{ width: '100%', aspectRatio: '16/9', objectFit: 'cover', borderRadius: '8px', marginBottom: '10px' }} />
          ) : (
            <div style={{ width: '100%', aspectRatio: '16/9', background: 'rgba(255,255,255,0.04)', borderRadius: '8px', marginBottom: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1.5">
                <rect x="2" y="2" width="20" height="20" rx="2" /><path d="M10 8l6 4-6 4V8z" />
              </svg>
            </div>
          )}
          <p style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8ed', margin: '0 0 4px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {video.video_name || 'Untitled Video'}
          </p>
          <div style={{ display: 'flex', gap: '8px', fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginBottom: '10px' }}>
            {video.avatar_name && <span>{video.avatar_name}</span>}
            {video.duration && <span>{video.duration}s</span>}
            {video.created_at && <span>{new Date(video.created_at).toLocaleDateString()}</span>}
          </div>
          {video.video_url && (
            <a href={video.video_url} download
              style={{ display: 'block', textAlign: 'center', padding: '8px', borderRadius: '8px', background: 'rgba(255,255,255,0.08)', color: '#2997ff', fontSize: '12px', textDecoration: 'none' }}>
              Download
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

export default function UGCVideoStudio() {
  const [activeTab, setActiveTab] = useState<'scripts' | 'create' | 'videos'>('scripts');
  const [scriptForVideo, setScriptForVideo] = useState('');

  const handleUseScript = useCallback((script: string) => {
    setScriptForVideo(script);
    setActiveTab('create');
  }, []);

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {/* Sub-tab bar */}
      <div className="card" style={{ padding: '6px', display: 'flex', gap: '4px', borderRadius: '14px' }}>
        {[
          { id: 'scripts', label: 'Generate Script' },
          { id: 'create', label: 'Create Video' },
          { id: 'videos', label: 'My Videos' },
        ].map(t => (
          <button key={t.id} type="button" onClick={() => setActiveTab(t.id as any)}
            style={{
              flex: 1, padding: '10px 16px', borderRadius: '10px', border: 'none',
              fontSize: '14px', fontWeight: activeTab === t.id ? 600 : 400, cursor: 'pointer',
              background: activeTab === t.id ? '#0071e3' : 'transparent',
              color: activeTab === t.id ? '#fff' : 'rgba(255,255,255,0.6)',
              transition: 'all 0.2s',
            }}
          >{t.label}</button>
        ))}
      </div>

      {activeTab === 'scripts' && <ScriptsTab onUseScript={handleUseScript} />}
      {activeTab === 'create' && <CreateVideoTab initialScript={scriptForVideo} />}
      {activeTab === 'videos' && <VideosTab />}
    </div>
  );
}
