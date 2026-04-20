'use client';
import { useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '@/lib/api';
import { VERTICALS, verticalOptions } from '@/lib/verticals';

type SubTab = 'angles' | 'ad-copy' | 'landing-page' | 'program-finder' | 'performance' | 'hook-library';

interface Angle {
  angle_name: string;
  headline: string;
  hook_line: string;
  emotional_trigger: string;
  recommended_style: string;
}

interface AdCopyVariation {
  platform: string;
  headline?: string;
  primary_text?: string;
  description?: string;
  cta?: string;
  [key: string]: unknown;
}

interface Program {
  name: string;
  reward: string;
  cookie_days: number;
  category: string;
  stars: number;
  url: string;
}

interface PerformanceRecord {
  campaign_name: string;
  vertical: string;
  spend: number;
  impressions: number;
  clicks: number;
  lp_views: number;
  conversions: number;
  revenue: number;
  ctr?: number;
  lp_ctr?: number;
  conv_rate?: number;
  cpc?: number;
  cpa?: number;
  roas?: number;
  epc?: number;
  recorded_at?: string;
}

interface Hook {
  hook_text: string;
  emotional_trigger: string;
  effectiveness_score: number;
  platform: string;
  source?: string;
  vertical?: string;
}

const inputStyle: React.CSSProperties = {
  background: 'rgba(255,255,255,0.08)',
  border: '1px solid rgba(255,255,255,0.12)',
  color: '#e8e8ed',
  borderRadius: '8px',
  padding: '10px 14px',
  fontSize: '14px',
  width: '100%',
  outline: 'none',
};

const labelStyle: React.CSSProperties = {
  fontSize: '13px',
  textTransform: 'uppercase',
  color: 'rgba(255,255,255,0.5)',
  letterSpacing: '0.6px',
  fontWeight: 600,
  marginBottom: '6px',
  display: 'block',
};

const primaryBtnStyle: React.CSSProperties = {
  background: '#0071e3',
  color: '#fff',
  border: 'none',
  borderRadius: '8px',
  padding: '12px 24px',
  fontSize: '14px',
  fontWeight: 600,
  cursor: 'pointer',
  letterSpacing: '-0.1px',
};

const secondaryBtnStyle: React.CSSProperties = {
  background: 'rgba(255,255,255,0.08)',
  color: '#e8e8ed',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '8px',
  padding: '8px 16px',
  fontSize: '13px',
  fontWeight: 500,
  cursor: 'pointer',
};

const subTabs: { id: SubTab; label: string }[] = [
  { id: 'angles', label: 'Angle Generator' },
  { id: 'ad-copy', label: 'Ad Copy' },
  { id: 'landing-page', label: 'Landing Page' },
  { id: 'program-finder', label: 'Program Finder' },
  { id: 'performance', label: 'Performance' },
  { id: 'hook-library', label: 'Hook Library' },
];

// Benchmarks for color-coding
const benchmarks: Record<string, { good: number; direction: 'higher' | 'lower' }> = {
  ctr: { good: 2, direction: 'higher' },
  lp_ctr: { good: 30, direction: 'higher' },
  conv_rate: { good: 3, direction: 'higher' },
  cpc: { good: 1.5, direction: 'lower' },
  cpa: { good: 50, direction: 'lower' },
  roas: { good: 2, direction: 'higher' },
  epc: { good: 0.5, direction: 'higher' },
};

function kpiColor(key: string, value: number): string {
  const b = benchmarks[key];
  if (!b) return '#e8e8ed';
  if (b.direction === 'higher') return value >= b.good ? '#30d158' : '#ff453a';
  return value <= b.good ? '#30d158' : '#ff453a';
}

function calcKPIs(m: { spend: number; impressions: number; clicks: number; lp_views: number; conversions: number; revenue: number }) {
  const ctr = m.impressions > 0 ? (m.clicks / m.impressions) * 100 : 0;
  const lp_ctr = m.lp_views > 0 ? (m.clicks / m.lp_views) * 100 : 0;
  const conv_rate = m.clicks > 0 ? (m.conversions / m.clicks) * 100 : 0;
  const cpc = m.clicks > 0 ? m.spend / m.clicks : 0;
  const cpa = m.conversions > 0 ? m.spend / m.conversions : 0;
  const roas = m.spend > 0 ? m.revenue / m.spend : 0;
  const epc = m.clicks > 0 ? m.revenue / m.clicks : 0;
  return { ctr, lp_ctr, conv_rate, cpc, cpa, roas, epc };
}

// ─── Angle Generator ────────────────────────────────────────────────
function AngleGeneratorTab({ onUseAngle }: { onUseAngle: (angle: Angle) => void }) {
  const [productName, setProductName] = useState('');
  const [description, setDescription] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [vertical, setVertical] = useState('home_insurance');
  const [angles, setAngles] = useState<Angle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const generate = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await axios.post(`${API_BASE_URL}/marketing/angles/generate`, {
        product_name: productName,
        product_description: description,
        target_audience: targetAudience,
        vertical,
      });
      setAngles(res.data.angles || res.data.data?.angles || res.data || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate angles';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={labelStyle}>Product Name</label>
          <input style={inputStyle} value={productName} onChange={e => setProductName(e.target.value)} placeholder="e.g. SuperFuel Energy" />
        </div>
        <div>
          <label style={labelStyle}>Target Audience</label>
          <input style={inputStyle} value={targetAudience} onChange={e => setTargetAudience(e.target.value)} placeholder="e.g. Men 30-50 who exercise" />
        </div>
      </div>
      <div style={{ marginBottom: '16px' }}>
        <label style={labelStyle}>Description</label>
        <textarea style={{ ...inputStyle, minHeight: '80px', resize: 'vertical' }} value={description} onChange={e => setDescription(e.target.value)} placeholder="Describe the product..." />
      </div>
      <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-end', marginBottom: '24px' }}>
        <div>
          <label style={labelStyle}>Vertical</label>
          <select style={inputStyle} value={vertical} onChange={e => setVertical(e.target.value)}>
            {Object.entries(verticalOptions()).map(([group, verts]) => (
              <optgroup key={group} label={group}>
                {verts.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
              </optgroup>
            ))}
          </select>
        </div>
        <button style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} onClick={generate} disabled={loading}>
          {loading ? 'Generating...' : 'Generate 10 Angles'}
        </button>
      </div>
      {error && <p style={{ color: '#ff453a', fontSize: '14px', marginBottom: '16px' }}>{error}</p>}
      {angles.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {angles.map((a, i) => (
            <div key={i} className="card" style={{ padding: '20px' }}>
              <h4 style={{ color: '#fff', fontSize: '16px', fontWeight: 600, margin: '0 0 8px' }}>{a.angle_name}</h4>
              <p style={{ color: '#e8e8ed', fontSize: '14px', margin: '0 0 4px' }}><strong>Headline:</strong> {a.headline}</p>
              <p style={{ color: 'rgba(255,255,255,0.7)', fontSize: '13px', margin: '0 0 4px' }}>{a.hook_line}</p>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', margin: '8px 0' }}>
                <span style={{ background: 'rgba(0,113,227,0.2)', color: '#64d2ff', borderRadius: '12px', padding: '2px 10px', fontSize: '11px' }}>{a.emotional_trigger}</span>
                <span style={{ background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.6)', borderRadius: '12px', padding: '2px 10px', fontSize: '11px' }}>{a.recommended_style}</span>
              </div>
              <button style={{ ...secondaryBtnStyle, marginTop: '8px', background: 'rgba(0,113,227,0.15)', color: '#0071e3' }} onClick={() => onUseAngle(a)}>
                Use This Angle
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Ad Copy ────────────────────────────────────────────────────────
function AdCopyTab({ selectedAngle }: { selectedAngle: Angle | null }) {
  const [vertical, setVertical] = useState('home_insurance');
  const [productName, setProductName] = useState('');
  const [description, setDescription] = useState('');
  const [angle, setAngle] = useState(selectedAngle?.angle_name || '');
  const [targetAudience, setTargetAudience] = useState('');
  const [platforms, setPlatforms] = useState<string[]>(['Meta']);
  const [hookText, setHookText] = useState(selectedAngle?.hook_line || '');
  const [transcript, setTranscript] = useState('');
  const [results, setResults] = useState<AdCopyVariation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<number | null>(null);

  const togglePlatform = (p: string) => {
    setPlatforms(prev => prev.includes(p) ? prev.filter(x => x !== p) : [...prev, p]);
  };

  const generate = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await axios.post(`${API_BASE_URL}/marketing/ad-copy/generate`, {
        product_name: productName,
        product_description: description,
        angle,
        target_audience: targetAudience,
        platforms,
        hook_text: hookText || undefined,
        transcript: transcript || undefined,
        vertical,
      });
      setResults(res.data.variations || res.data.data?.variations || res.data || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate ad copy';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setCopied(idx);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div>
      <div style={{ marginBottom: '16px' }}>
        <label style={labelStyle}>Vertical</label>
        <select style={inputStyle} value={vertical} onChange={e => setVertical(e.target.value)}>
          {Object.entries(verticalOptions()).map(([group, verts]) => (
            <optgroup key={group} label={group}>
              {verts.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </optgroup>
          ))}
        </select>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={labelStyle}>Product Name</label>
          <input style={inputStyle} value={productName} onChange={e => setProductName(e.target.value)} placeholder="Product name" />
        </div>
        <div>
          <label style={labelStyle}>Target Audience</label>
          <input style={inputStyle} value={targetAudience} onChange={e => setTargetAudience(e.target.value)} placeholder="Target audience" />
        </div>
      </div>
      <div style={{ marginBottom: '16px' }}>
        <label style={labelStyle}>Description</label>
        <textarea style={{ ...inputStyle, minHeight: '60px', resize: 'vertical' }} value={description} onChange={e => setDescription(e.target.value)} placeholder="Product description" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={labelStyle}>Angle</label>
          <input style={inputStyle} value={angle} onChange={e => setAngle(e.target.value)} placeholder="e.g. Fear of missing out" />
        </div>
        <div>
          <label style={labelStyle}>Hook Text (Optional)</label>
          <input style={inputStyle} value={hookText} onChange={e => setHookText(e.target.value)} placeholder="Opening hook" />
        </div>
      </div>
      <div style={{ marginBottom: '16px' }}>
        <label style={labelStyle}>Platforms</label>
        <div style={{ display: 'flex', gap: '10px' }}>
          {['Meta', 'TikTok', 'Google'].map(p => (
            <button
              key={p}
              onClick={() => togglePlatform(p)}
              style={{
                ...secondaryBtnStyle,
                background: platforms.includes(p) ? 'rgba(0,113,227,0.2)' : 'rgba(255,255,255,0.08)',
                color: platforms.includes(p) ? '#0071e3' : 'rgba(255,255,255,0.6)',
                border: platforms.includes(p) ? '1px solid rgba(0,113,227,0.4)' : '1px solid rgba(255,255,255,0.12)',
              }}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <div style={{ marginBottom: '24px' }}>
        <label style={labelStyle}>Transcript (Optional)</label>
        <textarea style={{ ...inputStyle, minHeight: '60px', resize: 'vertical' }} value={transcript} onChange={e => setTranscript(e.target.value)} placeholder="Paste existing transcript..." />
      </div>
      <button style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1, marginBottom: '24px' }} onClick={generate} disabled={loading}>
        {loading ? 'Generating...' : 'Generate Ad Copy'}
      </button>
      {error && <p style={{ color: '#ff453a', fontSize: '14px', marginBottom: '16px' }}>{error}</p>}
      {results.length > 0 && (
        <div style={{ display: 'grid', gap: '16px' }}>
          {results.map((v, i) => (
            <div key={i} className="card" style={{ padding: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span style={{ background: 'rgba(0,113,227,0.2)', color: '#64d2ff', borderRadius: '12px', padding: '2px 12px', fontSize: '12px', fontWeight: 600 }}>{v.platform}</span>
                <button
                  style={secondaryBtnStyle}
                  onClick={() => copyToClipboard(Object.entries(v).filter(([k]) => k !== 'platform').map(([k, val]) => `${k}: ${val}`).join('\n'), i)}
                >
                  {copied === i ? 'Copied!' : 'Copy'}
                </button>
              </div>
              {Object.entries(v).filter(([k]) => k !== 'platform').map(([key, val]) => (
                <div key={key} style={{ marginBottom: '8px' }}>
                  <span style={{ ...labelStyle, fontSize: '11px', marginBottom: '2px' }}>{key.replace(/_/g, ' ')}</span>
                  <p style={{ color: '#e8e8ed', fontSize: '14px', margin: 0 }}>{String(val)}</p>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Landing Page ───────────────────────────────────────────────────
function LandingPageTab() {
  const [mode, setMode] = useState<'generate' | 'analyze'>('generate');

  // Generate state
  const [vertical, setVertical] = useState('home_insurance');
  const [transcript, setTranscript] = useState('');
  const [offerUrl, setOfferUrl] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [productName, setProductName] = useState('');
  const [bonuses, setBonuses] = useState<string[]>(['']);
  const [pageType, setPageType] = useState('single');
  const [generatedHtml, setGeneratedHtml] = useState('');
  const [genLoading, setGenLoading] = useState(false);
  const [genError, setGenError] = useState('');

  // Analyze state
  const [analyzeUrl, setAnalyzeUrl] = useState('');
  const [analyzeHtml, setAnalyzeHtml] = useState('');
  const [spend, setSpend] = useState('');
  const [lpViews, setLpViews] = useState('');
  const [lpClicks, setLpClicks] = useState('');
  const [conversions, setConversions] = useState('');
  const [revenue, setRevenue] = useState('');
  const [analysis, setAnalysis] = useState<string>('');
  const [analysisKPIs, setAnalysisKPIs] = useState<Record<string, number> | null>(null);
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');

  const addBonus = () => setBonuses(prev => [...prev, '']);
  const updateBonus = (i: number, v: string) => setBonuses(prev => prev.map((b, idx) => idx === i ? v : b));
  const removeBonus = (i: number) => setBonuses(prev => prev.filter((_, idx) => idx !== i));

  const handleGenerate = async () => {
    setGenLoading(true);
    setGenError('');
    try {
      const res = await axios.post(`${API_BASE_URL}/marketing/landing-page/generate`, {
        vertical,
        transcript,
        offer_url: offerUrl,
        target_audience: targetAudience,
        product_name: productName,
        bonuses: bonuses.filter(b => b.trim()),
        page_type: pageType,
      });
      setGeneratedHtml(res.data.html || res.data.data?.html || '');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate landing page';
      setGenError(msg);
    } finally {
      setGenLoading(false);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzeLoading(true);
    setAnalyzeError('');
    try {
      const res = await axios.post(`${API_BASE_URL}/marketing/landing-page/analyze`, {
        url: analyzeUrl || undefined,
        html: analyzeHtml || undefined,
        metrics: {
          spend: parseFloat(spend) || 0,
          lp_views: parseInt(lpViews) || 0,
          lp_clicks: parseInt(lpClicks) || 0,
          conversions: parseInt(conversions) || 0,
          revenue: parseFloat(revenue) || 0,
        },
      });
      setAnalysis(res.data.analysis || res.data.data?.analysis || '');
      setAnalysisKPIs(res.data.kpis || res.data.data?.kpis || null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to analyze landing page';
      setAnalyzeError(msg);
    } finally {
      setAnalyzeLoading(false);
    }
  };

  const downloadHtml = () => {
    const blob = new Blob([generatedHtml], { type: 'text/html' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'landing-page.html';
    link.click();
  };

  return (
    <div>
      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '24px' }}>
        {(['generate', 'analyze'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              ...secondaryBtnStyle,
              background: mode === m ? 'rgba(0,113,227,0.2)' : 'rgba(255,255,255,0.08)',
              color: mode === m ? '#0071e3' : 'rgba(255,255,255,0.6)',
              border: mode === m ? '1px solid rgba(0,113,227,0.4)' : '1px solid rgba(255,255,255,0.12)',
              textTransform: 'capitalize',
            }}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === 'generate' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>Vertical (required)</label>
              <select style={inputStyle} value={vertical} onChange={e => setVertical(e.target.value)}>
                {Object.entries(verticalOptions()).map(([group, verts]) => (
                  <optgroup key={group} label={group}>
                    {verts.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Page Type</label>
              <select style={inputStyle} value={pageType} onChange={e => setPageType(e.target.value)}>
                <option value="single">Single Product</option>
                <option value="comparison">Comparison</option>
              </select>
            </div>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Ad Transcript</label>
            <textarea style={{ ...inputStyle, minHeight: '100px', resize: 'vertical' }} value={transcript} onChange={e => setTranscript(e.target.value)} placeholder="Paste your running ad's script/transcript" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>Offer URL</label>
              <input style={inputStyle} value={offerUrl} onChange={e => setOfferUrl(e.target.value)} placeholder="The offer page URL your traffic goes to" />
            </div>
            <div>
              <label style={labelStyle}>Target Audience</label>
              <input style={inputStyle} value={targetAudience} onChange={e => setTargetAudience(e.target.value)} placeholder="Target audience" />
            </div>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Product Name (optional, auto-derived from vertical if empty)</label>
            <input style={inputStyle} value={productName} onChange={e => setProductName(e.target.value)} placeholder="Leave blank to derive from vertical" />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Bonuses</label>
            {bonuses.map((b, i) => (
              <div key={i} style={{ display: 'flex', gap: '8px', marginBottom: '6px' }}>
                <input style={{ ...inputStyle, flex: 1 }} value={b} onChange={e => updateBonus(i, e.target.value)} placeholder={`Bonus ${i + 1}`} />
                {bonuses.length > 1 && (
                  <button style={{ ...secondaryBtnStyle, padding: '8px 12px' }} onClick={() => removeBonus(i)}>X</button>
                )}
              </div>
            ))}
            <button style={{ ...secondaryBtnStyle, marginTop: '4px' }} onClick={addBonus}>+ Add Bonus</button>
          </div>
          <button style={{ ...primaryBtnStyle, opacity: genLoading ? 0.6 : 1, marginBottom: '24px' }} onClick={handleGenerate} disabled={genLoading}>
            {genLoading ? 'Generating...' : 'Generate Landing Page'}
          </button>
          {genError && <p style={{ color: '#ff453a', fontSize: '14px', marginBottom: '16px' }}>{genError}</p>}
          {generatedHtml && (
            <div>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                <button style={secondaryBtnStyle} onClick={downloadHtml}>Download HTML</button>
                <button style={secondaryBtnStyle} onClick={() => { navigator.clipboard.writeText(generatedHtml); }}>Copy HTML</button>
              </div>
              <div className="card" style={{ padding: '0', overflow: 'hidden', borderRadius: '12px' }}>
                <iframe
                  srcDoc={generatedHtml}
                  style={{ width: '100%', height: '600px', border: 'none', background: '#fff', borderRadius: '12px' }}
                  title="Landing Page Preview"
                />
              </div>
            </div>
          )}
        </>
      )}

      {mode === 'analyze' && (
        <>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Landing Page URL</label>
            <input style={inputStyle} value={analyzeUrl} onChange={e => setAnalyzeUrl(e.target.value)} placeholder="https://yourlanding.page" />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Or Paste HTML</label>
            <textarea style={{ ...inputStyle, minHeight: '80px', resize: 'vertical' }} value={analyzeHtml} onChange={e => setAnalyzeHtml(e.target.value)} placeholder="Paste landing page HTML..." />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '12px', marginBottom: '24px' }}>
            <div>
              <label style={labelStyle}>Spend ($)</label>
              <input style={inputStyle} type="number" value={spend} onChange={e => setSpend(e.target.value)} placeholder="0" />
            </div>
            <div>
              <label style={labelStyle}>LP Views</label>
              <input style={inputStyle} type="number" value={lpViews} onChange={e => setLpViews(e.target.value)} placeholder="0" />
            </div>
            <div>
              <label style={labelStyle}>LP Clicks</label>
              <input style={inputStyle} type="number" value={lpClicks} onChange={e => setLpClicks(e.target.value)} placeholder="0" />
            </div>
            <div>
              <label style={labelStyle}>Conversions</label>
              <input style={inputStyle} type="number" value={conversions} onChange={e => setConversions(e.target.value)} placeholder="0" />
            </div>
            <div>
              <label style={labelStyle}>Revenue ($)</label>
              <input style={inputStyle} type="number" value={revenue} onChange={e => setRevenue(e.target.value)} placeholder="0" />
            </div>
          </div>
          <button style={{ ...primaryBtnStyle, opacity: analyzeLoading ? 0.6 : 1, marginBottom: '24px' }} onClick={handleAnalyze} disabled={analyzeLoading}>
            {analyzeLoading ? 'Analyzing...' : 'Analyze'}
          </button>
          {analyzeError && <p style={{ color: '#ff453a', fontSize: '14px', marginBottom: '16px' }}>{analyzeError}</p>}
          {analysisKPIs && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
              {Object.entries(analysisKPIs).map(([k, v]) => (
                <div key={k} className="card" style={{ padding: '16px', textAlign: 'center' }}>
                  <p style={{ ...labelStyle, marginBottom: '4px' }}>{k.replace(/_/g, ' ')}</p>
                  <p style={{ color: kpiColor(k, v), fontSize: '24px', fontWeight: 700, margin: 0 }}>
                    {k.includes('rate') || k === 'ctr' || k === 'lp_ctr' ? `${v.toFixed(2)}%` : k === 'roas' ? `${v.toFixed(2)}x` : `$${v.toFixed(2)}`}
                  </p>
                </div>
              ))}
            </div>
          )}
          {analysis && (
            <div className="card" style={{ padding: '20px' }}>
              <h4 style={{ color: '#fff', fontSize: '16px', fontWeight: 600, margin: '0 0 12px' }}>Analysis</h4>
              <p style={{ color: '#e8e8ed', fontSize: '14px', lineHeight: 1.6, margin: 0, whiteSpace: 'pre-wrap' }}>{analysis}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Program Finder ─────────────────────────────────────────────────
function ProgramFinderTab() {
  const [vertical, setVertical] = useState('home_insurance');
  const [query, setQuery] = useState('');
  const [rewardType, setRewardType] = useState('');
  const [tags, setTags] = useState('');
  const [minCookieDays, setMinCookieDays] = useState(0);
  const [sort, setSort] = useState('trending');
  const [results, setResults] = useState<Program[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const search = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (vertical) params.set('vertical', vertical);
      if (rewardType) params.set('reward_type', rewardType);
      if (tags) params.set('tags', tags);
      if (minCookieDays > 0) params.set('min_cookie_days', String(minCookieDays));
      params.set('sort', sort);
      const res = await axios.get(`${API_BASE_URL}/research/affiliate-search?${params.toString()}`);
      setResults(res.data.programs || res.data.data?.programs || res.data || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Search failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: '16px' }}>
        <label style={labelStyle}>Vertical</label>
        <select style={inputStyle} value={vertical} onChange={e => setVertical(e.target.value)}>
          {Object.entries(verticalOptions()).map(([group, verts]) => (
            <optgroup key={group} label={group}>
              {verts.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </optgroup>
          ))}
        </select>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={labelStyle}>Search</label>
          <input style={inputStyle} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search programs..." />
        </div>
        <div>
          <label style={labelStyle}>Reward Type</label>
          <select style={inputStyle} value={rewardType} onChange={e => setRewardType(e.target.value)}>
            <option value="">All</option>
            <option value="recurring">Recurring</option>
            <option value="one-time">One-Time</option>
            <option value="lifetime">Lifetime</option>
            <option value="CPL">CPL</option>
            <option value="CPC">CPC</option>
          </select>
        </div>
        <div>
          <label style={labelStyle}>Sort</label>
          <select style={inputStyle} value={sort} onChange={e => setSort(e.target.value)}>
            <option value="trending">Trending</option>
            <option value="new">New</option>
            <option value="top">Top</option>
          </select>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={labelStyle}>Tags</label>
          <input style={inputStyle} value={tags} onChange={e => setTags(e.target.value)} placeholder="e.g. health, finance" />
        </div>
        <div>
          <label style={labelStyle}>Min Cookie Days: {minCookieDays}</label>
          <input
            type="range"
            min="0"
            max="365"
            value={minCookieDays}
            onChange={e => setMinCookieDays(parseInt(e.target.value))}
            style={{ width: '100%', accentColor: '#0071e3', marginTop: '8px' }}
          />
        </div>
      </div>
      <button style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1, marginBottom: '24px' }} onClick={search} disabled={loading}>
        {loading ? 'Searching...' : 'Search Programs'}
      </button>
      {error && <p style={{ color: '#ff453a', fontSize: '14px', marginBottom: '16px' }}>{error}</p>}
      {results.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {['Name', 'Reward', 'Cookie Days', 'Category', 'Stars', ''].map(h => (
                  <th key={h} style={{ ...labelStyle, textAlign: 'left', padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((p, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.03)' }}>
                  <td style={{ color: '#e8e8ed', fontSize: '14px', padding: '12px 16px' }}>{p.name}</td>
                  <td style={{ color: '#30d158', fontSize: '14px', padding: '12px 16px', fontWeight: 600 }}>{p.reward}</td>
                  <td style={{ color: '#e8e8ed', fontSize: '14px', padding: '12px 16px' }}>{p.cookie_days}</td>
                  <td style={{ color: 'rgba(255,255,255,0.6)', fontSize: '14px', padding: '12px 16px' }}>{p.category}</td>
                  <td style={{ color: '#ffd60a', fontSize: '14px', padding: '12px 16px' }}>{'★'.repeat(p.stars)}{'☆'.repeat(5 - p.stars)}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <a href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: '#0071e3', fontSize: '13px', textDecoration: 'none' }}>View</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Performance ────────────────────────────────────────────────────
function PerformanceTab() {
  const [campaignName, setCampaignName] = useState('');
  const [vertical, setVertical] = useState('home_insurance');
  const [spend, setSpend] = useState('');
  const [impressions, setImpressions] = useState('');
  const [clicks, setClicks] = useState('');
  const [lpViews, setLpViews] = useState('');
  const [conversions, setConversions] = useState('');
  const [revenue, setRevenue] = useState('');
  const [kpis, setKpis] = useState<ReturnType<typeof calcKPIs> | null>(null);
  const [history, setHistory] = useState<PerformanceRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState('');
  const [csvRows, setCsvRows] = useState<Record<string, string>[]>([]);
  const [csvUploading, setCsvUploading] = useState(false);

  const record = async () => {
    setLoading(true);
    setError('');
    const metrics = {
      spend: parseFloat(spend) || 0,
      impressions: parseInt(impressions) || 0,
      clicks: parseInt(clicks) || 0,
      lp_views: parseInt(lpViews) || 0,
      conversions: parseInt(conversions) || 0,
      revenue: parseFloat(revenue) || 0,
    };
    try {
      await axios.post(`${API_BASE_URL}/research/performance/record`, {
        campaign_name: campaignName,
        vertical,
        ...metrics,
      });
      setKpis(calcKPIs(metrics));
      loadHistory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to record metrics';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const res = await axios.get(`${API_BASE_URL}/research/performance/history`);
      setHistory(res.data.records || res.data.data?.records || res.data || []);
    } catch {
      // Silently fail for history
    } finally {
      setHistoryLoading(false);
    }
  };

  const kpiLabels: Record<string, string> = {
    ctr: 'CTR',
    lp_ctr: 'LP CTR',
    conv_rate: 'Conv Rate',
    cpc: 'CPC',
    cpa: 'CPA',
    roas: 'ROAS',
    epc: 'EPC',
  };

  const formatKpi = (key: string, val: number) => {
    if (['ctr', 'lp_ctr', 'conv_rate'].includes(key)) return `${val.toFixed(2)}%`;
    if (key === 'roas') return `${val.toFixed(2)}x`;
    return `$${val.toFixed(2)}`;
  };

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={labelStyle}>Campaign Name</label>
          <input style={inputStyle} value={campaignName} onChange={e => setCampaignName(e.target.value)} placeholder="My Campaign" />
        </div>
        <div>
          <label style={labelStyle}>Vertical</label>
          <select style={inputStyle} value={vertical} onChange={e => setVertical(e.target.value)}>
            {Object.entries(verticalOptions()).map(([group, verts]) => (
              <optgroup key={group} label={group}>
                {verts.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
              </optgroup>
            ))}
          </select>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={labelStyle}>Spend ($)</label>
          <input style={inputStyle} type="number" value={spend} onChange={e => setSpend(e.target.value)} placeholder="0" />
        </div>
        <div>
          <label style={labelStyle}>Impressions</label>
          <input style={inputStyle} type="number" value={impressions} onChange={e => setImpressions(e.target.value)} placeholder="0" />
        </div>
        <div>
          <label style={labelStyle}>Clicks</label>
          <input style={inputStyle} type="number" value={clicks} onChange={e => setClicks(e.target.value)} placeholder="0" />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginBottom: '24px' }}>
        <div>
          <label style={labelStyle}>LP Views</label>
          <input style={inputStyle} type="number" value={lpViews} onChange={e => setLpViews(e.target.value)} placeholder="0" />
        </div>
        <div>
          <label style={labelStyle}>Conversions</label>
          <input style={inputStyle} type="number" value={conversions} onChange={e => setConversions(e.target.value)} placeholder="0" />
        </div>
        <div>
          <label style={labelStyle}>Revenue ($)</label>
          <input style={inputStyle} type="number" value={revenue} onChange={e => setRevenue(e.target.value)} placeholder="0" />
        </div>
      </div>
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '24px' }}>
        <button style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} onClick={record} disabled={loading}>
          {loading ? 'Recording...' : 'Record Metrics'}
        </button>
        <label style={{ ...secondaryBtnStyle, display: 'inline-block' }}>
          Upload CSV
          <input
            type="file"
            accept=".csv"
            style={{ display: 'none' }}
            onChange={e => {
              const file = e.target.files?.[0];
              if (!file) return;
              const reader = new FileReader();
              reader.onload = evt => {
                const text = evt.target?.result as string;
                const lines = text.trim().split('\n');
                if (lines.length < 2) return;
                const headers = lines[0].split(',').map(h => h.trim());
                const rows = lines.slice(1).map(line => {
                  const vals = line.split(',').map(v => v.trim());
                  const row: Record<string, string> = {};
                  headers.forEach((h, i) => { row[h] = vals[i] || ''; });
                  return row;
                });
                setCsvRows(rows);
              };
              reader.readAsText(file);
              e.target.value = '';
            }}
          />
        </label>
      </div>

      {csvRows.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <h4 style={{ color: '#fff', fontSize: '15px', fontWeight: 600, margin: '0 0 12px' }}>CSV Preview ({csvRows.length} rows)</h4>
          <div style={{ overflowX: 'auto', marginBottom: '12px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {Object.keys(csvRows[0]).map(h => (
                    <th key={h} style={{ ...labelStyle, textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {csvRows.map((row, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.03)' }}>
                    {Object.values(row).map((v, j) => (
                      <td key={j} style={{ color: '#e8e8ed', fontSize: '13px', padding: '8px 10px' }}>{v}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              style={{ ...primaryBtnStyle, opacity: csvUploading ? 0.6 : 1 }}
              disabled={csvUploading}
              onClick={async () => {
                setCsvUploading(true);
                setError('');
                try {
                  for (const row of csvRows) {
                    await axios.post(`${API_BASE_URL}/research/performance/record`, {
                      campaign_name: row.campaign_name || '',
                      vertical,
                      spend: parseFloat(row.spend) || 0,
                      impressions: parseInt(row.impressions) || 0,
                      clicks: parseInt(row.clicks) || 0,
                      lp_views: parseInt(row.lp_views) || 0,
                      conversions: parseInt(row.conversions) || 0,
                      revenue: parseFloat(row.revenue) || 0,
                    });
                  }
                  setCsvRows([]);
                  loadHistory();
                } catch (err: unknown) {
                  const msg = err instanceof Error ? err.message : 'Failed to upload CSV rows';
                  setError(msg);
                } finally {
                  setCsvUploading(false);
                }
              }}
            >
              {csvUploading ? 'Submitting...' : `Submit ${csvRows.length} Rows`}
            </button>
            <button style={secondaryBtnStyle} onClick={() => setCsvRows([])}>Cancel</button>
          </div>
        </div>
      )}

      {error && <p style={{ color: '#ff453a', fontSize: '14px', marginBottom: '16px' }}>{error}</p>}
      {kpis && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '32px' }}>
          {Object.entries(kpis).map(([k, v]) => (
            <div key={k} className="card" style={{ padding: '16px', textAlign: 'center' }}>
              <p style={{ ...labelStyle, marginBottom: '4px' }}>{kpiLabels[k] || k}</p>
              <p style={{ color: kpiColor(k, v), fontSize: '24px', fontWeight: 700, margin: 0 }}>
                {formatKpi(k, v)}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* History */}
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h3 style={{ color: '#fff', fontSize: '18px', fontWeight: 600, margin: 0 }}>Campaign History</h3>
          <button style={secondaryBtnStyle} onClick={loadHistory} disabled={historyLoading}>
            {historyLoading ? 'Loading...' : 'Load History'}
          </button>
        </div>
        {history.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Campaign', 'Vertical', 'Spend', 'Clicks', 'Conv', 'Revenue', 'ROAS', 'CPA'].map(h => (
                    <th key={h} style={{ ...labelStyle, textAlign: 'left', padding: '10px 12px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {history.map((r, i) => {
                  const rKpis = calcKPIs(r);
                  return (
                    <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.03)' }}>
                      <td style={{ color: '#e8e8ed', fontSize: '13px', padding: '10px 12px' }}>{r.campaign_name}</td>
                      <td style={{ color: 'rgba(255,255,255,0.6)', fontSize: '13px', padding: '10px 12px' }}>{r.vertical}</td>
                      <td style={{ color: '#e8e8ed', fontSize: '13px', padding: '10px 12px' }}>${r.spend.toFixed(2)}</td>
                      <td style={{ color: '#e8e8ed', fontSize: '13px', padding: '10px 12px' }}>{r.clicks}</td>
                      <td style={{ color: '#e8e8ed', fontSize: '13px', padding: '10px 12px' }}>{r.conversions}</td>
                      <td style={{ color: '#30d158', fontSize: '13px', padding: '10px 12px', fontWeight: 600 }}>${r.revenue.toFixed(2)}</td>
                      <td style={{ color: kpiColor('roas', rKpis.roas), fontSize: '13px', padding: '10px 12px', fontWeight: 600 }}>{rKpis.roas.toFixed(2)}x</td>
                      <td style={{ color: kpiColor('cpa', rKpis.cpa), fontSize: '13px', padding: '10px 12px', fontWeight: 600 }}>${rKpis.cpa.toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Hook Library ───────────────────────────────────────────────────
function HookLibraryTab() {
  const [vertical, setVertical] = useState('');
  const [platform, setPlatform] = useState('All');
  const [hooks, setHooks] = useState<Hook[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);

  // Add hook form
  const [newHookText, setNewHookText] = useState('');
  const [newVertical, setNewVertical] = useState('home_insurance');
  const [newPlatform, setNewPlatform] = useState('YouTube');
  const [newTrigger, setNewTrigger] = useState('');
  const [newScore, setNewScore] = useState('7');

  const loadHooks = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (vertical) params.set('vertical', vertical);
      if (platform && platform !== 'All') params.set('platform', platform);
      const res = await axios.get(`${API_BASE_URL}/research/hooks?${params.toString()}`);
      setHooks(res.data.hooks || res.data.data?.hooks || res.data || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load hooks';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const addHook = async () => {
    try {
      await axios.post(`${API_BASE_URL}/research/hooks`, {
        hook_text: newHookText,
        vertical: newVertical,
        platform: newPlatform,
        emotional_trigger: newTrigger,
        effectiveness_score: parseInt(newScore),
      });
      setShowAddForm(false);
      setNewHookText('');
      setNewTrigger('');
      loadHooks();
    } catch {
      // Error adding hook
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-end', marginBottom: '24px', flexWrap: 'wrap' }}>
        <div>
          <label style={labelStyle}>Vertical</label>
          <select style={inputStyle} value={vertical} onChange={e => setVertical(e.target.value)}>
            <option value="">All</option>
            {Object.entries(verticalOptions()).map(([group, verts]) => (
              <optgroup key={group} label={group}>
                {verts.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
              </optgroup>
            ))}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Platform</label>
          <select style={inputStyle} value={platform} onChange={e => setPlatform(e.target.value)}>
            <option value="All">All</option>
            <option value="YouTube">YouTube</option>
            <option value="TikTok">TikTok</option>
            <option value="Instagram">Instagram</option>
          </select>
        </div>
        <button style={{ ...primaryBtnStyle, opacity: loading ? 0.6 : 1 }} onClick={loadHooks} disabled={loading}>
          {loading ? 'Loading...' : 'Load Hooks'}
        </button>
        <button style={secondaryBtnStyle} onClick={() => setShowAddForm(!showAddForm)}>
          {showAddForm ? 'Cancel' : '+ Add Hook'}
        </button>
      </div>

      {showAddForm && (
        <div className="card" style={{ padding: '20px', marginBottom: '24px' }}>
          <h4 style={{ color: '#fff', fontSize: '16px', fontWeight: 600, margin: '0 0 16px' }}>Add New Hook</h4>
          <div style={{ marginBottom: '12px' }}>
            <label style={labelStyle}>Hook Text</label>
            <textarea style={{ ...inputStyle, minHeight: '60px', resize: 'vertical' }} value={newHookText} onChange={e => setNewHookText(e.target.value)} placeholder="Enter hook text..." />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>Vertical</label>
              <select style={inputStyle} value={newVertical} onChange={e => setNewVertical(e.target.value)}>
                {Object.entries(verticalOptions()).map(([group, verts]) => (
                  <optgroup key={group} label={group}>
                    {verts.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Platform</label>
              <select style={inputStyle} value={newPlatform} onChange={e => setNewPlatform(e.target.value)}>
                <option value="YouTube">YouTube</option>
                <option value="TikTok">TikTok</option>
                <option value="Instagram">Instagram</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>Emotional Trigger</label>
              <input style={inputStyle} value={newTrigger} onChange={e => setNewTrigger(e.target.value)} placeholder="e.g. Fear" />
            </div>
            <div>
              <label style={labelStyle}>Score (1-10)</label>
              <input style={inputStyle} type="number" min="1" max="10" value={newScore} onChange={e => setNewScore(e.target.value)} />
            </div>
          </div>
          <button style={primaryBtnStyle} onClick={addHook}>Save Hook</button>
        </div>
      )}

      {error && <p style={{ color: '#ff453a', fontSize: '14px', marginBottom: '16px' }}>{error}</p>}

      {hooks.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {hooks.map((h, i) => (
            <div key={i} className="card" style={{ padding: '20px' }}>
              <p style={{ color: '#e8e8ed', fontSize: '15px', lineHeight: 1.5, margin: '0 0 12px', fontStyle: 'italic' }}>
                &ldquo;{h.hook_text}&rdquo;
              </p>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ background: 'rgba(0,113,227,0.2)', color: '#64d2ff', borderRadius: '12px', padding: '2px 10px', fontSize: '11px' }}>
                  {h.emotional_trigger}
                </span>
                <span style={{ background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.6)', borderRadius: '12px', padding: '2px 10px', fontSize: '11px' }}>
                  {h.platform}
                </span>
                {h.source && (
                  <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '11px' }}>{h.source}</span>
                )}
                <span style={{
                  marginLeft: 'auto',
                  color: h.effectiveness_score >= 7 ? '#30d158' : h.effectiveness_score >= 4 ? '#ffd60a' : '#ff453a',
                  fontSize: '14px',
                  fontWeight: 700,
                }}>
                  {h.effectiveness_score}/10
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main MarketingHub Component ────────────────────────────────────
export default function MarketingHub() {
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('angles');
  const [selectedAngle, setSelectedAngle] = useState<Angle | null>(null);

  const handleUseAngle = (angle: Angle) => {
    setSelectedAngle(angle);
    setActiveSubTab('ad-copy');
  };

  return (
    <div>
      {/* Sub-tab bar */}
      <div style={{
        display: 'flex',
        gap: '6px',
        marginBottom: '24px',
        background: 'rgba(255,255,255,0.06)',
        borderRadius: '12px',
        padding: '4px',
        flexWrap: 'wrap',
      }}>
        {subTabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id)}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              border: 'none',
              fontSize: '13px',
              fontWeight: activeSubTab === tab.id ? 600 : 400,
              cursor: 'pointer',
              transition: 'all 0.2s',
              background: activeSubTab === tab.id ? '#0071e3' : 'transparent',
              color: activeSubTab === tab.id ? '#fff' : 'rgba(255,255,255,0.6)',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeSubTab === 'angles' && <AngleGeneratorTab onUseAngle={handleUseAngle} />}
      {activeSubTab === 'ad-copy' && <AdCopyTab selectedAngle={selectedAngle} />}
      {activeSubTab === 'landing-page' && <LandingPageTab />}
      {activeSubTab === 'program-finder' && <ProgramFinderTab />}
      {activeSubTab === 'performance' && <PerformanceTab />}
      {activeSubTab === 'hook-library' && <HookLibraryTab />}
    </div>
  );
}
