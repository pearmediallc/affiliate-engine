'use client';

import { useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '@/lib/api';
import { VERTICALS, VERTICAL_GROUPS, verticalOptions } from '@/lib/verticals';

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

export default function LandingPageStudio() {
  const [vertical, setVertical] = useState('home_insurance');
  const [mode, setMode] = useState<'generate' | 'analyze'>('generate');

  // Generate state
  const [productName, setProductName] = useState('');
  const [description, setDescription] = useState('');
  const [url, setUrl] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [bonuses, setBonuses] = useState<string[]>(['']);
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
  const [analysis, setAnalysis] = useState('');
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
        product_name: productName,
        description,
        url,
        target_audience: targetAudience,
        bonuses: bonuses.filter(b => b.trim()),
        vertical,
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

  const groups = verticalOptions();

  return (
    <div className="space-y-6">
      {/* Vertical selector */}
      <div className="card" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '20px' }}>
        <label style={labelStyle}>Vertical</label>
        <select
          value={vertical}
          onChange={e => setVertical(e.target.value)}
          style={{ ...inputStyle, maxWidth: '300px' }}
        >
          {Object.entries(groups).map(([group, verts]) => (
            <optgroup key={group} label={group}>
              {verts.map(v => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: '8px' }}>
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

      {/* Generate mode */}
      {mode === 'generate' && (
        <div className="card" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '24px' }}>
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
            <label style={labelStyle}>Description / Transcript</label>
            <textarea style={{ ...inputStyle, minHeight: '80px', resize: 'vertical' }} value={description} onChange={e => setDescription(e.target.value)} placeholder="Product description or video transcript" />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Offer URL</label>
            <input style={inputStyle} value={url} onChange={e => setUrl(e.target.value)} placeholder="https://..." />
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
          <button style={{ ...primaryBtnStyle, opacity: genLoading ? 0.6 : 1 }} onClick={handleGenerate} disabled={genLoading}>
            {genLoading ? 'Generating...' : 'Generate Landing Page'}
          </button>
          {genError && <p style={{ color: '#ff453a', fontSize: '14px', marginTop: '12px' }}>{genError}</p>}
          {generatedHtml && (
            <div style={{ marginTop: '24px' }}>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                <button style={secondaryBtnStyle} onClick={downloadHtml}>Download HTML</button>
                <button style={secondaryBtnStyle} onClick={() => { navigator.clipboard.writeText(generatedHtml); }}>Copy HTML</button>
              </div>
              <div style={{ overflow: 'hidden', borderRadius: '12px' }}>
                <iframe
                  srcDoc={generatedHtml}
                  style={{ width: '100%', height: '600px', border: 'none', background: '#fff', borderRadius: '12px' }}
                  title="Landing Page Preview"
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Analyze mode */}
      {mode === 'analyze' && (
        <div className="card" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '24px' }}>
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
          <button style={{ ...primaryBtnStyle, opacity: analyzeLoading ? 0.6 : 1 }} onClick={handleAnalyze} disabled={analyzeLoading}>
            {analyzeLoading ? 'Analyzing...' : 'Analyze Landing Page'}
          </button>
          {analyzeError && <p style={{ color: '#ff453a', fontSize: '14px', marginTop: '12px' }}>{analyzeError}</p>}
          {analysis && (
            <div style={{ marginTop: '24px' }}>
              <div style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '10px', padding: '16px', fontSize: '14px', color: '#e8e8ed', whiteSpace: 'pre-wrap', lineHeight: '1.6', maxHeight: '400px', overflowY: 'auto' }}>
                {analysis}
              </div>
              <button
                style={{ ...secondaryBtnStyle, marginTop: '12px' }}
                onClick={() => navigator.clipboard.writeText(analysis)}
              >
                Copy Analysis
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
