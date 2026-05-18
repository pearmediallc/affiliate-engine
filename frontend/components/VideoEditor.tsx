'use client';

import { useState, useRef } from 'react';
import { editVideo, autoCaptionVideo, optimizePrompt, recordOutcome, API_HOST } from '../lib/api';

const labelStyle: React.CSSProperties = {
  fontSize: '12px', fontWeight: 600, color: 'rgba(255,255,255,0.45)',
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '6px', display: 'block',
};

const COLOR_GRADES = ['none', 'cinematic', 'warm', 'cool', 'vivid'];
const CAPTION_STYLES = [
  { id: 'tiktok', label: 'TikTok / Reels (2 words, center)' },
  { id: 'karaoke', label: 'Karaoke highlight (word lights up)' },
  { id: 'bold_center', label: 'Bold center (3 words)' },
  { id: 'subtitle', label: 'Subtitle (bottom, classic)' },
];
const MUSIC_MOODS = ['', 'motivational', 'upbeat', 'energetic', 'calm', 'dramatic', 'corporate', 'inspiring'];
const ASPECTS = ['16:9', '9:16', '1:1'];

interface HarnessBlock {
  feedback: string;
  suggestions: string[];
  gate_stopped: string;
}

interface CaptionResult {
  urls: Record<string, string>;
  srt: string;
  ass?: string;
  transcript: string;
  word_count?: number;
  caption_count: number;
}

export default function VideoEditor() {
  const [file, setFile] = useState<File | null>(null);
  const [colorGrade, setColorGrade] = useState('none');
  const [captionText, setCaptionText] = useState('');
  const [captionStyle, setCaptionStyle] = useState('tiktok');
  const [musicMood, setMusicMood] = useState('');
  const [selectedAspects, setSelectedAspects] = useState<string[]>(['16:9', '9:16', '1:1']);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState<Record<string, string> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Auto-caption state
  const [acWordsPerLine, setAcWordsPerLine] = useState(2);
  const [acStyle, setAcStyle] = useState('tiktok');
  const [acAspects, setAcAspects] = useState<string[]>(['9:16']);
  const [acProcessing, setAcProcessing] = useState(false);
  const [acError, setAcError] = useState('');
  const [acResult, setAcResult] = useState<CaptionResult | null>(null);
  const [acEventId, setAcEventId] = useState<string | null>(null);

  // Harness block state — shown when gate rejects a prompt
  const [harnessBlock, setHarnessBlock] = useState<HarnessBlock | null>(null);
  const [harnessChecking, setHarnessChecking] = useState(false);

  function toggleAcAspect(a: string) {
    setAcAspects(prev => prev.includes(a) ? prev.filter(x => x !== a) : [...prev, a]);
  }

  async function handleAutoCaption() {
    if (!file) return;
    setAcProcessing(true); setAcError(''); setAcResult(null); setHarnessBlock(null);

    try {
      // ── Harness gate: check before spending API budget ──────────────────
      setHarnessChecking(true);
      let eventId: string | null = null;
      try {
        const harnessRes = await optimizePrompt({
          raw_prompt: `Auto-caption ${file.name} with ${acStyle} style, ${acWordsPerLine} words per line`,
          feature: 'caption',
          vertical: 'general',
          params: { caption_style: acStyle, words_per_line: acWordsPerLine },
        });
        if (!harnessRes.data?.approved) {
          setHarnessBlock({
            feedback: harnessRes.data?.feedback || 'Please refine your caption settings.',
            suggestions: harnessRes.data?.suggestions || [],
            gate_stopped: harnessRes.data?.gate_stopped || 'unknown',
          });
          return;
        }
        eventId = harnessRes.data?.event_id || null;
        setAcEventId(eventId);
      } catch (_) {
        // Harness failure is non-fatal — proceed with generation
      } finally {
        setHarnessChecking(false);
      }

      // ── Actual captioning call ──────────────────────────────────────────
      const startTime = Date.now();
      const fd = new FormData();
      fd.append('video', file);
      fd.append('words_per_line', String(acWordsPerLine));
      fd.append('caption_style', acStyle);
      fd.append('output_aspects', acAspects.join(',') || '9:16');
      const r = await autoCaptionVideo(fd);
      const elapsed = (Date.now() - startTime) / 1000;

      if (r.success && r.data?.urls) {
        const resolved: Record<string, string> = {};
        for (const [k, url] of Object.entries(r.data.urls as Record<string, string>)) {
          resolved[k] = (url as string).startsWith('http') ? url as string : `${API_HOST}${url}`;
        }
        setAcResult({ ...r.data, urls: resolved });

        // Record outcome as approved (result produced)
        if (eventId) {
          recordOutcome({ event_id: eventId, outcome: 'approved', time_to_action_sec: elapsed }).catch(() => {});
        }
      } else {
        setAcError(r.message || 'Auto-caption failed');
        if (eventId) {
          recordOutcome({ event_id: eventId, outcome: 'rejected' }).catch(() => {});
        }
      }
    } catch (e: any) {
      setAcError(e?.response?.data?.detail || e.message || 'Failed');
    } finally {
      setAcProcessing(false);
      setHarnessChecking(false);
    }
  }

  function handleDownload(url: string, aspect: string) {
    if (acEventId) {
      recordOutcome({ event_id: acEventId, outcome: 'downloaded' }).catch(() => {});
    }
    const a = document.createElement('a');
    a.href = url; a.download = `caption_${aspect.replace(':', 'x')}.mp4`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }

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

      {/* ── Auto-Caption ── */}
      <div className="card" style={{ padding: '20px' }}>
        <div style={{ marginBottom: '16px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#e8e8ed', margin: 0 }}>Auto-Caption</h3>
          <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.35)', marginTop: '4px' }}>
            Transcribes speech with Whisper AI and burns accurate timed captions — like professional caption tools.
            Upload a video above first.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '16px' }}>
          {/* Words per line */}
          <div>
            <label style={labelStyle}>Words per caption line</label>
            <div style={{ display: 'flex', gap: '6px' }}>
              {[3, 5, 7].map(n => (
                <button key={n} onClick={() => setAcWordsPerLine(n)}
                  style={{
                    padding: '7px 16px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                    fontSize: '14px', fontWeight: 600, transition: 'all 0.15s',
                    background: acWordsPerLine === n ? '#0071e3' : 'rgba(255,255,255,0.08)',
                    color: acWordsPerLine === n ? '#fff' : 'rgba(255,255,255,0.6)',
                  }}>{n}</button>
              ))}
            </div>
          </div>

          {/* Style */}
          <div>
            <label style={labelStyle}>Caption style</label>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {CAPTION_STYLES.map(s => (
                <button key={s.id} onClick={() => setAcStyle(s.id)}
                  style={{
                    padding: '7px 14px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                    fontSize: '13px', transition: 'all 0.15s',
                    background: acStyle === s.id ? '#0071e3' : 'rgba(255,255,255,0.08)',
                    color: acStyle === s.id ? '#fff' : 'rgba(255,255,255,0.6)',
                  }}>{s.label}</button>
              ))}
            </div>
          </div>

          {/* Export formats */}
          <div>
            <label style={labelStyle}>Export format</label>
            <div style={{ display: 'flex', gap: '6px' }}>
              {ASPECTS.map(a => (
                <button key={a} onClick={() => toggleAcAspect(a)}
                  style={{
                    padding: '7px 14px', borderRadius: '8px',
                    border: `1px solid ${acAspects.includes(a) ? '#0071e3' : 'rgba(255,255,255,0.12)'}`,
                    cursor: 'pointer', fontSize: '13px', fontWeight: 500, transition: 'all 0.15s',
                    background: acAspects.includes(a) ? 'rgba(0,113,227,0.15)' : 'rgba(255,255,255,0.04)',
                    color: acAspects.includes(a) ? '#2997ff' : 'rgba(255,255,255,0.5)',
                  }}>{a}</button>
              ))}
            </div>
          </div>
        </div>

        <button
          className="btn-primary"
          onClick={handleAutoCaption}
          disabled={!file || acProcessing || harnessChecking}
          style={{ fontSize: '14px', marginBottom: '12px' }}
        >
          {harnessChecking ? 'Checking prompt quality...' : acProcessing ? 'Transcribing & burning captions...' : 'Transcribe & Caption'}
        </button>

        {harnessChecking && (
          <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.35)', marginBottom: '8px' }}>
            Harness engine validating — ensures quality before spending API budget
          </p>
        )}

        {acProcessing && (
          <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', marginBottom: '8px' }}>
            Extracting audio → Whisper word-level transcription → burning {acStyle} captions — 30–90s
          </p>
        )}

        {/* Harness block — gate stopped generation */}
        {harnessBlock && (
          <div style={{ background: 'rgba(255,159,10,0.08)', border: '1px solid rgba(255,159,10,0.3)', borderRadius: '12px', padding: '16px', marginBottom: '8px' }}>
            <p style={{ fontSize: '13px', color: '#ff9f0a', fontWeight: 600, marginBottom: '8px' }}>
              Prompt Quality Gate — {harnessBlock.gate_stopped}
            </p>
            <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.7)', marginBottom: '12px' }}>
              {harnessBlock.feedback}
            </p>
            {harnessBlock.suggestions.length > 0 && (
              <ul style={{ margin: 0, paddingLeft: '18px' }}>
                {harnessBlock.suggestions.map((s, i) => (
                  <li key={i} style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', marginBottom: '4px' }}>{s}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {acError && (
          <div style={{ background: 'rgba(255,69,58,0.1)', border: '1px solid rgba(255,69,58,0.3)', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#ff6961', marginBottom: '8px' }}>
            {acError}
          </div>
        )}

        {/* Results */}
        {acResult && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ background: 'rgba(48,209,88,0.08)', border: '1px solid rgba(48,209,88,0.2)', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#30d158' }}>
              {acResult.word_count ? `${acResult.word_count} words transcribed · ` : ''}{acResult.caption_count} caption lines burned
            </div>

            {/* Transcript */}
            <div>
              <label style={labelStyle}>Full transcript</label>
              <div style={{
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '8px', padding: '12px', fontSize: '13px', color: 'rgba(255,255,255,0.7)',
                lineHeight: 1.6, maxHeight: '120px', overflowY: 'auto',
              }}>
                {acResult.transcript}
              </div>
            </div>

            {/* Download files */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <label style={{ ...labelStyle, marginBottom: 0 }}>Download</label>
              <a
                href={`data:text/plain;charset=utf-8,${encodeURIComponent(acResult.srt)}`}
                download="captions.srt"
                style={{ padding: '5px 12px', borderRadius: '7px', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', fontSize: '12px', textDecoration: 'none', border: '1px solid rgba(255,255,255,0.12)' }}
              >
                .srt
              </a>
              {acResult.ass && (
                <a
                  href={`data:text/plain;charset=utf-8,${encodeURIComponent(acResult.ass)}`}
                  download="captions.ass"
                  style={{ padding: '5px 12px', borderRadius: '7px', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', fontSize: '12px', textDecoration: 'none', border: '1px solid rgba(255,255,255,0.12)' }}
                >
                  .ass (karaoke)
                </a>
              )}
            </div>

            {/* Video outputs */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
              {Object.entries(acResult.urls).map(([aspect, url]) => (
                <div key={aspect} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '12px', overflow: 'hidden' }}>
                  <div style={{
                    aspectRatio: aspect === '9:16' ? '9/16' : aspect === '1:1' ? '1/1' : '16/9',
                    maxHeight: aspect === '9:16' ? '300px' : '180px',
                    background: '#000',
                  }}>
                    <video src={url} controls style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                  </div>
                  <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8ed' }}>{aspect}</span>
                    <button onClick={() => handleDownload(url, aspect)} style={{
                      padding: '5px 12px', borderRadius: '7px', background: '#0071e3', color: '#fff',
                      fontSize: '12px', border: 'none', cursor: 'pointer', fontWeight: 500,
                    }}>Download</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
