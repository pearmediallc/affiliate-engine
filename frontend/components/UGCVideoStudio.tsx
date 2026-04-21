'use client';
import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  const [videoResult, setVideoResult] = useState<{ video_url?: string; material_id?: string } | null>(null);
  const [error, setError] = useState('');
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [elapsedTime, setElapsedTime] = useState(0);
  const elapsedRef = useRef<NodeJS.Timeout | null>(null);

  const addLog = (msg: string) => {
    const time = new Date().toLocaleTimeString();
    setStatusLog(prev => [...prev, `[${time}] ${msg}`]);
  };

  const startTimer = () => {
    setElapsedTime(0);
    elapsedRef.current = setInterval(() => setElapsedTime(prev => prev + 1), 1000);
  };
  const stopTimer = () => {
    if (elapsedRef.current) { clearInterval(elapsedRef.current); elapsedRef.current = null; }
  };
  const formatTime = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;

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

  // Sanitize script for TikTok Avatar API
  const sanitizeScript = (text: string): string => {
    return text
      .replace(/[""]/g, '')       // Remove smart quotes
      .replace(/['']/g, '')       // Remove smart apostrophes
      .replace(/["']/g, '')       // Remove regular quotes
      .replace(/[→←↑↓]/g, '')    // Remove arrows
      .replace(/[\u{1F000}-\u{1FFFF}]/gu, '') // Remove emojis
      .replace(/[^\x20-\x7E\n]/g, '') // Remove non-ASCII except newlines
      .replace(/\n+/g, ' ')      // Replace newlines with spaces
      .replace(/\s+/g, ' ')      // Collapse multiple spaces
      .trim()
      .substring(0, 2000);        // Max 2000 chars
  };

  const handleCreate = async () => {
    if (!selectedAvatar || !script.trim()) return;
    setIsCreating(true);
    setError('');
    setVideoResult(null);
    setStatusLog([]);
    startTimer();

    try {
      const cleanScript = sanitizeScript(script);
      if (cleanScript.length < 10) {
        setError('Script is too short after sanitization. Use plain text without emojis or special characters.');
        setIsCreating(false);
        stopTimer();
        return;
      }

      addLog('Sending video creation request to TikTok...');
      const res = await axios.post(`${API_BASE_URL}/tiktok/videos/create`, {
        avatar_id: selectedAvatar,
        script: cleanScript,
        video_name: videoName || undefined,
      });

      addLog('TikTok accepted the request. Extracting task ID...');

      // Extract task IDs - try every possible location
      const topData = res.data;
      const innerData = topData?.data || {};

      let taskIds: string[] = [];

      // TikTok returns: {"list": [{"task_id": "xxx"}]} — extract from list items
      if (Array.isArray(innerData?.list)) {
        taskIds = innerData.list.map((item: any) => item?.task_id).filter(Boolean);
      }
      // Also try other field names as fallback
      if (taskIds.length === 0 && innerData?.task_id_list && Array.isArray(innerData.task_id_list)) {
        taskIds = innerData.task_id_list;
      }
      if (taskIds.length === 0 && innerData?.task_id) {
        taskIds = [innerData.task_id];
      }
      if (taskIds.length === 0 && topData?.task_id) {
        taskIds = [topData.task_id];
      }

      // Filter out empty values
      taskIds = taskIds.filter((id: string) => id && id.length > 0);

      addLog(`Task ID: ${taskIds[0] || 'none'}`);

      if (taskIds.length === 0) {
        setError(`Video task created but no task ID returned. Response: ${JSON.stringify(innerData).substring(0, 200)}`);
        setIsCreating(false);
        stopTimer();
        addLog('ERROR: No task ID returned from TikTok');
        return;
      }

      addLog('Video is queued on TikTok. Starting status checks...');

      // Start polling with progress tracking
      setError('');
      const startTime = Date.now();
      let attempts = 0;
      const maxAttempts = 60;

      const updateProgress = () => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
      };

      const pollInterval = setInterval(async () => {
        attempts++;
        try {
          addLog(`Checking status... (attempt ${attempts}/60)`);

          const statusRes = await axios.get(
            `${API_BASE_URL}/tiktok/videos/status?task_ids=${encodeURIComponent(JSON.stringify(taskIds))}`
          );

          const statusData = statusRes.data?.data || statusRes.data;
          const taskList = statusData?.task_list || statusData?.list || [];
          const task = taskList.length > 0 ? taskList[0] : statusData;
          const rawStatus = task?.status || statusData?.status || '';
          const status = rawStatus.toUpperCase();

          if (status === 'UNKNOWN' || status === 'PROCESSING' || status === 'PENDING' || status === '') {
            addLog(`Status: Processing... TikTok is generating your video`);
          } else if (status === 'SUCCESS' || status === 'COMPLETED' || status === 'COMPLETE') {
            clearInterval(pollInterval);
            stopTimer();
            addLog('Video generated successfully!');
            const videoInfo = task?.video_info || task?.video || task;
            setVideoResult({
              video_url: videoInfo?.video_url || videoInfo?.url || videoInfo?.preview_url || '',
              material_id: videoInfo?.material_id || '',
            });
            setIsCreating(false);
          } else if (status === 'FAILED' || status === 'ERROR' || status === 'CANCELLED') {
            clearInterval(pollInterval);
            stopTimer();
            const reason = task?.fail_reason || task?.error || 'Unknown reason';
            addLog(`FAILED: ${reason}`);
            setError(`Video creation failed: ${reason}`);
            setIsCreating(false);
          } else if (attempts >= maxAttempts) {
            clearInterval(pollInterval);
            stopTimer();
            addLog('Timed out — check My Videos tab');
            setError(`Timed out after ${updateProgress()}. Check "My Videos" tab.`);
            setIsCreating(false);
          } else {
            addLog(`Status: ${rawStatus || 'waiting...'}`);
          }

        } catch (pollErr: any) {
          addLog(`Connection error (attempt ${attempts})`);
          if (attempts >= 5) {
            clearInterval(pollInterval);
            stopTimer();
            setError(`Connection lost after ${updateProgress()}. The video may still be generating - check "My Videos" tab.`);
            setIsCreating(false);
          }
        }
      }, 5000);

    } catch (err: any) {
      console.error('[UGC] Create error:', err);
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
          placeholder="Write naturally as if someone is speaking to camera. Example: Hello everyone. I want to share something that could save you hundreds of dollars on your home insurance. Most people are overpaying because they never compare rates..."
          style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', height: '140px', resize: 'none', outline: 'none' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '6px' }}>
          <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>
            Plain text only. No emojis, quotes, or special characters. ~500 chars = 30s video.
          </p>
          <p style={{ fontSize: '12px', color: script.length > 2000 ? '#ff6b6b' : 'rgba(255,255,255,0.4)' }}>{script.length}/2000</p>
        </div>
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
          width: '100%', padding: '14px', borderRadius: '10px', border: 'none',
          fontSize: '16px', fontWeight: 500, cursor: 'pointer',
          background: '#0071e3', color: '#fff',
          opacity: (isCreating || !selectedAvatar || !script.trim()) ? 0.5 : 1,
        }}>
        {isCreating ? 'Creating Video...' : 'Create Speaking Video'}
      </button>
      {/* Real-time status log */}
      {(isCreating || statusLog.length > 0) && (
        <div className="card" style={{ padding: '16px', marginTop: '12px' }}>
          {/* Header with timer */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              {isCreating && (
                <div style={{ width: '14px', height: '14px', border: '2px solid rgba(255,255,255,0.2)', borderTopColor: '#0071e3', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
              )}
              <span style={{ fontSize: '13px', fontWeight: 600, color: isCreating ? '#2997ff' : '#30d158' }}>
                {isCreating ? 'Generating Video' : 'Complete'}
              </span>
            </div>
            <span style={{ fontSize: '20px', fontWeight: 700, color: '#fff', fontVariantNumeric: 'tabular-nums' }}>
              {formatTime(elapsedTime)}
            </span>
          </div>

          {/* Progress bar estimate (assume 2 min avg) */}
          {isCreating && (
            <div style={{ height: '4px', background: 'rgba(255,255,255,0.08)', borderRadius: '2px', marginBottom: '12px', overflow: 'hidden' }}>
              <div style={{
                height: '100%', background: 'linear-gradient(90deg, #0071e3, #2997ff)',
                borderRadius: '2px', transition: 'width 1s linear',
                width: `${Math.min(elapsedTime / 120 * 100, 95)}%`,
              }} />
            </div>
          )}

          {/* Status log entries */}
          <div style={{ maxHeight: '160px', overflowY: 'auto', fontSize: '12px', fontFamily: 'monospace' }}>
            {statusLog.map((line, i) => (
              <p key={i} style={{
                margin: '2px 0', padding: '2px 0',
                color: line.includes('ERROR') || line.includes('FAILED') ? '#ff6b6b'
                  : line.includes('successfully') || line.includes('SUCCESS') ? '#30d158'
                  : line.includes('Processing') ? '#ffd60a'
                  : 'rgba(255,255,255,0.5)',
              }}>
                {line}
              </p>
            ))}
          </div>

          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {error && <p style={{ fontSize: '13px', color: '#ff6b6b', textAlign: 'center' }}>{error}</p>}

      {/* Video Result - constrained size for portrait 9:16 */}
      {videoResult && videoResult.video_url && (
        <div className="card" style={{ padding: '20px' }}>
          <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '12px' }}>Result</p>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '12px' }}>
            <video src={videoResult.video_url} controls playsInline
              style={{
                width: '100%', maxWidth: '360px', maxHeight: '640px',
                borderRadius: '10px', background: '#000', objectFit: 'contain',
              }} />
          </div>
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
  const [playingId, setPlayingId] = useState<string | null>(null);

  useEffect(() => {
    loadVideos();
  }, []);

  const loadVideos = async () => {
    setIsLoading(true);
    setError('');
    try {
      // Merge TikTok's list + our locally saved jobs (job queue) so users never lose videos
      const [ttRes, jobsRes] = await Promise.all([
        axios.get(`${API_BASE_URL}/tiktok/videos/list`).catch(() => ({ data: { data: {} } })),
        axios.get(`${API_BASE_URL}/jobs/my?job_type=ugc_video&limit=50`).catch(() => ({ data: { data: { jobs: [] } } })),
      ]);
      const data = ttRes.data?.data || ttRes.data;
      console.log('[UGC] Videos list raw data:', JSON.stringify(data).substring(0, 500));
      const rawList = data?.video_list || data?.list || data?.videos || [];
      // Normalize field names from TikTok API
      const ttVideos = rawList.map((v: any) => ({
        video_id: v.video_id || v.id || '',
        video_name: v.file_name || v.video_name || v.name || 'Untitled Video',
        avatar_name: v.avatar_name || v.avatar_id || '',
        duration: v.duration || v.video_duration || 0,
        created_at: v.created_time || v.created_at || v.create_time || '',
        thumbnail_url: v.cover_url || v.thumbnail_url || v.preview_url || '',
        video_url: v.video_url || v.preview_url || v.download_url || '',
        status: v.status || '',
      }));

      // Include job-queue videos (covers cases where TikTok list is slow/empty + provides local backups)
      const jobs = jobsRes.data?.data?.jobs || [];
      const jobVideos: Video[] = jobs
        .filter((j: any) => j.status === 'completed' && (j.result_url || j.result_data?.video_url))
        .map((j: any) => ({
          video_id: j.id,
          video_name: j.input_data?.video_name || 'UGC Video',
          avatar_name: j.input_data?.avatar_id || '',
          duration: 0,
          created_at: j.created_at || '',
          thumbnail_url: j.result_data?.cover_url || '',
          video_url: j.result_url?.startsWith('/') ? `${API_BASE_URL.replace('/api/v1', '')}${j.result_url}` : (j.result_url || j.result_data?.video_url || ''),
          status: 'SUCCESS',
        }));

      // Dedupe by video_url, prefer job-queue copies (local backups)
      const merged: Video[] = [];
      const seen = new Set<string>();
      for (const v of [...jobVideos, ...ttVideos]) {
        const key = v.video_url || v.video_id;
        if (key && !seen.has(key)) {
          seen.add(key);
          merged.push(v);
        }
      }
      console.log('[UGC] Merged videos:', merged.length, '(tt:', ttVideos.length, 'jobs:', jobVideos.length, ')');
      setVideos(merged);
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
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '16px' }}>
      {videos.map((video, i) => {
        const key = video.video_id || `v${i}`;
        const isPlaying = playingId === key;
        return (
          <div key={key} className="card" style={{ padding: '12px', overflow: 'hidden' }}>
            {/* Thumbnail OR inline player (9:16 portrait for TikTok UGC) */}
            <div style={{
              position: 'relative', width: '100%', aspectRatio: '9/16',
              background: 'rgba(0,0,0,0.6)', borderRadius: '8px', marginBottom: '10px',
              overflow: 'hidden', cursor: isPlaying ? 'default' : 'pointer',
            }}
            onClick={() => !isPlaying && video.video_url && setPlayingId(key)}>
              {isPlaying && video.video_url ? (
                <video src={video.video_url} controls autoPlay playsInline
                  style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }} />
              ) : video.thumbnail_url ? (
                <>
                  <img src={`${API_BASE_URL}/tiktok/proxy-image?url=${encodeURIComponent(video.thumbnail_url)}`} alt={video.video_name || 'Video'}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    onError={(e) => {
                      const img = e.target as HTMLImageElement;
                      img.style.display = 'none';
                      const fallback = img.nextElementSibling as HTMLElement;
                      if (fallback) fallback.style.display = 'flex';
                    }} />
                  <div style={{
                    display: 'none', width: '100%', height: '100%',
                    alignItems: 'center', justifyContent: 'center',
                    background: 'linear-gradient(135deg, #0071e3 0%, #2997ff 100%)',
                  }}>
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="rgba(255,255,255,0.9)">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  </div>
                  {video.video_url && (
                    <div style={{
                      position: 'absolute', inset: 0, display: 'flex',
                      alignItems: 'center', justifyContent: 'center',
                      background: 'rgba(0,0,0,0.25)', transition: 'background 0.2s',
                    }}>
                      <div style={{
                        width: '48px', height: '48px', borderRadius: '50%',
                        background: 'rgba(255,255,255,0.95)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="#000">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div style={{
                  width: '100%', height: '100%', display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  background: 'linear-gradient(135deg, #0071e3 0%, #2997ff 100%)',
                }}>
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="rgba(255,255,255,0.9)">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </div>
              )}
            </div>
            <p style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8ed', margin: '0 0 4px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {video.video_name || 'Untitled Video'}
            </p>
            <div style={{ display: 'flex', gap: '8px', fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginBottom: '10px', flexWrap: 'wrap' }}>
              {video.duration ? <span>{video.duration}s</span> : null}
              {video.status && <span style={{ color: video.status.toUpperCase() === 'SUCCESS' ? '#30d158' : video.status.toUpperCase() === 'FAILED' ? '#ff6b6b' : '#ffd60a' }}>{video.status}</span>}
              {video.created_at && <span>{new Date(video.created_at).toLocaleDateString()}</span>}
            </div>
            <div style={{ display: 'flex', gap: '6px' }}>
              {video.video_url && !isPlaying && (
                <button type="button" onClick={() => setPlayingId(key)}
                  style={{ flex: 1, padding: '8px', borderRadius: '8px', border: 'none', background: '#0071e3', color: '#fff', fontSize: '12px', fontWeight: 500, cursor: 'pointer' }}>
                  Play
                </button>
              )}
              {video.video_url && (
                <a href={video.video_url} download target="_blank" rel="noopener noreferrer"
                  style={{ flex: 1, textAlign: 'center', padding: '8px', borderRadius: '8px', background: 'rgba(255,255,255,0.08)', color: '#2997ff', fontSize: '12px', textDecoration: 'none', fontWeight: 500 }}>
                  Download
                </a>
              )}
            </div>
          </div>
        );
      })}
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
