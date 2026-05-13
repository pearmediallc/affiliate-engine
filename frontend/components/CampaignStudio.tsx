'use client';

import { useState, useEffect } from 'react';
import {
  createCampaign, getCampaign, runBriefing, runScripting, runStoryboarding,
  startGeneration, runEditing, listCharacters, listSceneSettings,
  createCharacter, createSceneSetting, listVariations, listCampaigns,
  planVariants, createVariation, API_HOST,
} from '../lib/api';
import { VERTICALS } from '../lib/verticals';
import VariationGrid from './VariationGrid';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Campaign {
  id: string; name: string; vertical: string; status: string;
  brief_text: string; analyzed_brief: Record<string, any> | null;
  script: string | null; storyboard: any[] | null; shots: any[];
  total_cost_usd: number; created_at: string;
}
interface Character {
  id: string; name: string; description: string;
  portrait_url: string | null; consistency_prompt: string | null;
}
interface SceneSetting {
  id: string; name: string; description: string;
  location_type: string; reference_image_url: string | null;
}

// ─── Shared styles (match app design system) ──────────────────────────────────

const labelStyle: React.CSSProperties = {
  fontSize: '12px', fontWeight: 600, color: 'rgba(255,255,255,0.45)',
  textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: '6px', display: 'block',
};
const sectionTitle: React.CSSProperties = {
  fontSize: '16px', fontWeight: 600, color: '#e8e8ed', marginBottom: '4px',
};
const subText: React.CSSProperties = {
  fontSize: '13px', color: 'rgba(255,255,255,0.45)',
};

function tabBtn(active: boolean): React.CSSProperties {
  return {
    padding: '8px 18px', borderRadius: '8px', border: 'none', cursor: 'pointer',
    fontSize: '14px', fontWeight: active ? 600 : 400, transition: 'all 0.15s',
    background: active ? '#0071e3' : 'rgba(255,255,255,0.07)',
    color: active ? '#fff' : 'rgba(255,255,255,0.6)',
  };
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function CampaignStudio() {
  const [tab, setTab] = useState<'campaigns' | 'characters' | 'locations'>('campaigns');

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [sceneSets, setSceneSets] = useState<SceneSetting[]>([]);
  const [variations, setVariations] = useState<any[]>([]);

  useEffect(() => { loadAll(); }, []);

  // Poll when generating
  useEffect(() => {
    if (selected?.status !== 'generating') return;
    const t = setInterval(async () => {
      try {
        const r = await getCampaign(selected.id);
        const up = r.data as Campaign;
        setSelected(up);
        setCampaigns(prev => prev.map(c => c.id === up.id ? up : c));
        if (up.status !== 'generating') clearInterval(t);
      } catch {}
    }, 8000);
    return () => clearInterval(t);
  }, [selected?.status]);

  async function loadAll() {
    const [cRes, chrRes, sRes] = await Promise.allSettled([
      listCampaigns(), listCharacters(), listSceneSettings(),
    ]);
    if (cRes.status === 'fulfilled') setCampaigns(cRes.value.data?.campaigns || []);
    if (chrRes.status === 'fulfilled') setCharacters(chrRes.value.data?.characters || []);
    if (sRes.status === 'fulfilled') setSceneSets(sRes.value.data?.settings || []);
  }

  async function reloadCampaign(id: string) {
    const r = await getCampaign(id);
    const up = r.data as Campaign;
    setSelected(up);
    setCampaigns(prev => prev.map(c => c.id === up.id ? up : c));
    return up;
  }

  async function reloadVariations(campaignId: string) {
    try {
      const r = await listVariations(campaignId);
      setVariations(r.data?.variations || []);
    } catch {}
  }

  return (
    <div style={{ color: '#e8e8ed', minHeight: '100vh' }}>

      {/* ── Page header ──────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: '24px', padding: '20px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2 style={{ fontSize: '22px', fontWeight: 700, color: '#e8e8ed', margin: 0 }}>Campaign Studio</h2>
            <p style={{ ...subText, marginTop: '3px' }}>Brief → Script → Storyboard → Generate → Edit → Variations</p>
          </div>
          {/* Tab switcher */}
          <div style={{ display: 'flex', gap: '6px' }}>
            {(['campaigns', 'characters', 'locations'] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={tabBtn(tab === t)}>
                {t === 'campaigns' ? 'Campaigns' : t === 'characters' ? 'Characters' : 'Locations'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Campaigns tab ───────────────────────────────────── */}
      {tab === 'campaigns' && (
        <CampaignsTab
          campaigns={campaigns}
          selected={selected}
          characters={characters}
          sceneSets={sceneSets}
          variations={variations}
          onSelect={c => { setSelected(c); reloadVariations(c.id); }}
          onCampaignCreated={c => { setCampaigns(prev => [c, ...prev]); setSelected(c); }}
          onReload={id => reloadCampaign(id)}
          onVariationsReload={id => reloadVariations(id)}
        />
      )}

      {/* ── Characters tab ──────────────────────────────────── */}
      {tab === 'characters' && (
        <CharactersTab
          characters={characters}
          onCreated={c => setCharacters(prev => [c, ...prev])}
        />
      )}

      {/* ── Locations tab ───────────────────────────────────── */}
      {tab === 'locations' && (
        <LocationsTab
          sceneSets={sceneSets}
          onCreated={s => setSceneSets(prev => [s, ...prev])}
        />
      )}
    </div>
  );
}

// ─── Campaigns tab ────────────────────────────────────────────────────────────

function CampaignsTab({
  campaigns, selected, characters, sceneSets, variations,
  onSelect, onCampaignCreated, onReload, onVariationsReload,
}: {
  campaigns: Campaign[]; selected: Campaign | null; characters: Character[]; sceneSets: SceneSetting[];
  variations: any[]; onSelect: (c: Campaign) => void; onCampaignCreated: (c: Campaign) => void;
  onReload: (id: string) => Promise<Campaign>; onVariationsReload: (id: string) => void;
}) {
  const [showNewForm, setShowNewForm] = useState(false);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: '20px', alignItems: 'start' }}>

      {/* Campaign list */}
      <div className="card" style={{ padding: '12px', minHeight: '300px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', padding: '0 4px' }}>
          <span style={{ ...labelStyle, margin: 0 }}>Campaigns ({campaigns.length})</span>
          <button className="btn-primary" style={{ fontSize: '12px', padding: '5px 10px' }}
            onClick={() => setShowNewForm(true)}>+ New</button>
        </div>
        {campaigns.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <p style={subText}>No campaigns yet</p>
            <button className="btn-primary" style={{ marginTop: '12px', fontSize: '13px' }}
              onClick={() => setShowNewForm(true)}>Create first</button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {campaigns.map(c => (
              <button key={c.id} onClick={() => onSelect(c)}
                style={{
                  width: '100%', textAlign: 'left', padding: '10px 12px', borderRadius: '8px',
                  border: selected?.id === c.id ? '1px solid #0071e3' : '1px solid transparent',
                  background: selected?.id === c.id ? 'rgba(0,113,227,0.12)' : 'rgba(255,255,255,0.04)',
                  cursor: 'pointer', transition: 'all 0.15s',
                }}>
                <div style={{ fontSize: '13px', fontWeight: 500, color: '#e8e8ed', marginBottom: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <StatusPill status={c.status} />
                  <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>{c.vertical}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Campaign detail */}
      <div>
        {!selected ? (
          <div className="card" style={{ textAlign: 'center', padding: '60px 24px' }}>
            <p style={{ fontSize: '32px', marginBottom: '12px' }}>+</p>
            <p style={sectionTitle}>Select or create a campaign</p>
            <p style={{ ...subText, marginBottom: '20px' }}>Each phase is independently testable</p>
            <button className="btn-primary" onClick={() => setShowNewForm(true)}>Create Campaign</button>
          </div>
        ) : (
          <CampaignDetail
            campaign={selected}
            characters={characters}
            sceneSets={sceneSets}
            variations={variations}
            onReload={() => onReload(selected.id)}
            onVariationsReload={() => onVariationsReload(selected.id)}
          />
        )}
      </div>

      {showNewForm && (
        <NewCampaignModal
          onClose={() => setShowNewForm(false)}
          onCreated={c => { onCampaignCreated(c); setShowNewForm(false); }}
        />
      )}
    </div>
  );
}

// ─── Campaign detail — all phases as separate cards ───────────────────────────

function CampaignDetail({ campaign, characters, sceneSets, variations, onReload, onVariationsReload }: {
  campaign: Campaign; characters: Character[]; sceneSets: SceneSetting[];
  variations: any[]; onReload: () => Promise<Campaign>; onVariationsReload: () => void;
}) {
  const completedShots = campaign.shots?.filter((s: any) => s.status === 'completed').length || 0;
  const totalShots = campaign.shots?.length || 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* Campaign header */}
      <div className="card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: 700, color: '#e8e8ed', margin: '0 0 6px' }}>{campaign.name}</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <StatusPill status={campaign.status} />
              <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.4)' }}>{campaign.vertical}</span>
              {campaign.total_cost_usd > 0 && (
                <span style={{ fontSize: '13px', color: '#30d158' }}>${campaign.total_cost_usd.toFixed(4)} spent</span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '6px' }}>
            {campaign.brief_text && (
              <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {campaign.brief_text}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Phase 1 — Brief Analysis */}
      <PhaseCard
        number={1}
        title="Brief Analysis"
        description="AI analyzes your reference video/image and extracts creative insights"
        status={campaign.analyzed_brief ? 'done' : 'pending'}
      >
        <BriefPhase campaign={campaign} onReload={onReload} />
      </PhaseCard>

      {/* Phase 2 — Script */}
      <PhaseCard
        number={2}
        title="Script Generation"
        description="Gemini writes a direct-response ad script from the brief"
        status={campaign.script ? 'done' : 'pending'}
      >
        <ScriptPhase campaign={campaign} onReload={onReload} />
      </PhaseCard>

      {/* Phase 3 — Storyboard */}
      <PhaseCard
        number={3}
        title="Storyboard"
        description="Shot-by-shot breakdown with model routing and cost estimate"
        status={campaign.storyboard ? 'done' : 'pending'}
      >
        <StoryboardPhase campaign={campaign} characters={characters} sceneSets={sceneSets} onReload={onReload} />
      </PhaseCard>

      {/* Phase 4 — Video Generation */}
      <PhaseCard
        number={4}
        title="Video Generation"
        description="Multi-provider parallel shot generation (Veo, Higgsfield, Replicate)"
        status={campaign.status === 'generating' ? 'running' : campaign.status === 'editing' || campaign.status === 'review' || campaign.status === 'completed' ? 'done' : 'pending'}
      >
        <GeneratePhase campaign={campaign} completedShots={completedShots} totalShots={totalShots} onReload={onReload} />
      </PhaseCard>

      {/* Phase 5 — Auto-Edit */}
      <PhaseCard
        number={5}
        title="Auto-Edit"
        description="Stitch shots, color grade, LUFS audio normalization, export 9:16 / 1:1 / 16:9"
        status={campaign.status === 'editing' ? 'running' : campaign.status === 'review' || campaign.status === 'completed' ? 'done' : 'pending'}
      >
        <EditPhase campaign={campaign} onReload={onReload} />
      </PhaseCard>

      {/* Phase 6 — Variations & Review */}
      <PhaseCard
        number={6}
        title="Variations & Review"
        description="Create hook/character/style variants, approve or reject each cut"
        status={variations.length > 0 ? 'done' : 'pending'}
      >
        <ReviewPhase campaign={campaign} variations={variations} onVariationsReload={onVariationsReload} />
      </PhaseCard>
    </div>
  );
}

// ─── Phase wrapper card ───────────────────────────────────────────────────────

function PhaseCard({ number, title, description, status, children }: {
  number: number; title: string; description: string;
  status: 'pending' | 'running' | 'done'; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);

  const statusColors: Record<string, string> = {
    pending: 'rgba(255,255,255,0.25)',
    running: '#ff9f0a',
    done: '#30d158',
  };

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Header row */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', textAlign: 'left', padding: '16px 20px',
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: '14px',
        }}
      >
        <div style={{
          width: '28px', height: '28px', borderRadius: '50%', flexShrink: 0,
          background: status === 'done' ? 'rgba(48,209,88,0.15)' : status === 'running' ? 'rgba(255,159,10,0.15)' : 'rgba(255,255,255,0.07)',
          border: `1px solid ${statusColors[status]}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '12px', fontWeight: 700,
          color: statusColors[status],
        }}>
          {status === 'done' ? '✓' : status === 'running' ? '…' : number}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '15px', fontWeight: 600, color: '#e8e8ed' }}>{title}</span>
            {status === 'running' && (
              <span style={{ fontSize: '11px', color: '#ff9f0a', background: 'rgba(255,159,10,0.12)', padding: '2px 8px', borderRadius: '999px' }}>Running</span>
            )}
            {status === 'done' && (
              <span style={{ fontSize: '11px', color: '#30d158', background: 'rgba(48,209,88,0.1)', padding: '2px 8px', borderRadius: '999px' }}>Complete</span>
            )}
          </div>
          <p style={{ ...subText, marginTop: '2px' }}>{description}</p>
        </div>
        <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.3)', flexShrink: 0 }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ padding: '4px 20px 20px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ─── Phase 1: Brief ───────────────────────────────────────────────────────────

function BriefPhase({ campaign, onReload }: { campaign: Campaign; onReload: () => Promise<Campaign> }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function run() {
    setLoading(true); setError('');
    try { await runBriefing(campaign.id); await onReload(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  const brief = campaign.analyzed_brief;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '14px' }}>
      {/* Input brief */}
      {campaign.brief_text && (
        <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '12px 14px' }}>
          <span style={labelStyle}>Brief text</span>
          <p style={{ fontSize: '14px', color: '#e8e8ed' }}>{campaign.brief_text}</p>
        </div>
      )}

      {/* Analyzed brief */}
      {brief ? (
        <div style={{ background: 'rgba(48,209,88,0.05)', border: '1px solid rgba(48,209,88,0.2)', borderRadius: '10px', padding: '14px' }}>
          <span style={labelStyle}>AI-analyzed brief</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginTop: '8px' }}>
            {[
              ['Hook style', brief.hook_style],
              ['Ad arc', brief.ad_arc],
              ['Visual rhythm', brief.visual_rhythm],
              ['Color palette', brief.color_palette],
              ['Camera style', brief.camera_style],
              ['CTA style', brief.cta_style],
            ].filter(([, v]) => v).map(([k, v]) => (
              <div key={k as string}>
                <p style={{ ...labelStyle, marginBottom: '2px' }}>{k as string}</p>
                <p style={{ fontSize: '13px', color: '#e8e8ed' }}>{v as string}</p>
              </div>
            ))}
          </div>
          {brief.key_insights?.length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <p style={labelStyle}>Key insights</p>
              <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {brief.key_insights.map((ins: string, i: number) => (
                  <li key={i} style={{ fontSize: '13px', color: '#e8e8ed' }}>{ins}</li>
                ))}
              </ul>
            </div>
          )}
          <button className="btn-secondary" style={{ marginTop: '14px', fontSize: '13px', padding: '7px 14px' }}
            onClick={run} disabled={loading}>
            {loading ? 'Re-analyzing...' : 'Re-analyze reference'}
          </button>
        </div>
      ) : (
        <div>
          <p style={{ ...subText, marginBottom: '12px' }}>
            Analyzes reference video/image with Pixtral AI to extract hook style, ad arc, visual rhythm, and key insights.
            {!campaign.brief_text && !campaign.analyzed_brief && ' Add a reference video/image when creating the campaign.'}
          </p>
          <button className="btn-primary" onClick={run} disabled={loading} style={{ fontSize: '14px' }}>
            {loading ? 'Analyzing...' : 'Analyze Brief'}
          </button>
        </div>
      )}
      {error && <ErrorBanner msg={error} />}
    </div>
  );
}

// ─── Phase 2: Script ──────────────────────────────────────────────────────────

function ScriptPhase({ campaign, onReload }: { campaign: Campaign; onReload: () => Promise<Campaign> }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [duration, setDuration] = useState(30);
  const [extra, setExtra] = useState('');

  async function run() {
    setLoading(true); setError('');
    try { await runScripting(campaign.id, duration, extra); await onReload(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '14px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: '12px' }}>
        <div>
          <label style={labelStyle}>Duration</label>
          <select value={duration} onChange={e => setDuration(+e.target.value)}
            className="input" style={{ fontSize: '14px', padding: '8px 12px' }}>
            {[15, 20, 30, 45, 60].map(d => <option key={d} value={d}>{d} seconds</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Extra instructions (optional)</label>
          <input type="text" value={extra} onChange={e => setExtra(e.target.value)}
            placeholder="e.g. Focus on a fear-based hook, add 3 testimonial points"
            className="input" style={{ fontSize: '14px', padding: '8px 12px' }} />
        </div>
      </div>

      {campaign.script ? (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={labelStyle}>Generated script</span>
            <button className="btn-secondary" style={{ fontSize: '12px', padding: '5px 10px' }}
              onClick={run} disabled={loading}>
              {loading ? 'Writing...' : 'Regenerate'}
            </button>
          </div>
          <pre style={{
            background: 'rgba(255,255,255,0.04)', borderRadius: '10px',
            padding: '14px', fontSize: '13px', color: '#e8e8ed',
            whiteSpace: 'pre-wrap', fontFamily: 'inherit', lineHeight: '1.6',
            maxHeight: '360px', overflowY: 'auto', margin: 0,
          }}>{campaign.script}</pre>
        </div>
      ) : (
        <div>
          <p style={{ ...subText, marginBottom: '12px' }}>
            Gemini writes a punchy direct-response script with [HOOK], [PROBLEM], [SOLUTION], [PROOF], [CTA] structure.
          </p>
          <button className="btn-primary" onClick={run} disabled={loading} style={{ fontSize: '14px' }}>
            {loading ? 'Writing script...' : 'Generate Script'}
          </button>
        </div>
      )}
      {error && <ErrorBanner msg={error} />}
    </div>
  );
}

// ─── Phase 3: Storyboard ─────────────────────────────────────────────────────

function StoryboardPhase({ campaign, characters, sceneSets, onReload }: {
  campaign: Campaign; characters: Character[]; sceneSets: SceneSetting[];
  onReload: () => Promise<Campaign>;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [charIds, setCharIds] = useState<string[]>([]);
  const [settingIds, setSettingIds] = useState<string[]>([]);
  const [duration, setDuration] = useState(30);

  async function run() {
    setLoading(true); setError('');
    try { await runStoryboarding(campaign.id, charIds, settingIds, duration); await onReload(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  function toggleId(id: string, ids: string[], setIds: (v: string[]) => void) {
    setIds(ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '14px' }}>

      {/* Controls */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 140px', gap: '12px' }}>
        <div>
          <label style={labelStyle}>Characters</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {characters.length === 0
              ? <p style={subText}>No characters — add some in the Characters tab</p>
              : characters.map(c => (
                <CheckRow key={c.id} label={c.name} checked={charIds.includes(c.id)}
                  onChange={() => toggleId(c.id, charIds, setCharIds)} />
              ))}
          </div>
        </div>
        <div>
          <label style={labelStyle}>Locations</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {sceneSets.length === 0
              ? <p style={subText}>No locations — add some in the Locations tab</p>
              : sceneSets.map(s => (
                <CheckRow key={s.id} label={s.name} checked={settingIds.includes(s.id)}
                  onChange={() => toggleId(s.id, settingIds, setSettingIds)} />
              ))}
          </div>
        </div>
        <div>
          <label style={labelStyle}>Target duration</label>
          <select value={duration} onChange={e => setDuration(+e.target.value)}
            className="input" style={{ fontSize: '14px', padding: '8px 12px' }}>
            {[15, 20, 30, 45, 60].map(d => <option key={d} value={d}>{d}s</option>)}
          </select>
        </div>
      </div>

      {/* Shot list */}
      {campaign.storyboard ? (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
            <span style={labelStyle}>{campaign.storyboard.length} shots — est. ${campaign.total_cost_usd?.toFixed(3) || '...'}</span>
            <button className="btn-secondary" style={{ fontSize: '12px', padding: '5px 10px' }}
              onClick={run} disabled={loading}>{loading ? 'Generating...' : 'Regenerate'}</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '340px', overflowY: 'auto' }}>
            {campaign.storyboard.map((shot: any, i: number) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'flex-start', gap: '12px',
                background: 'rgba(255,255,255,0.04)', borderRadius: '8px', padding: '10px 12px',
              }}>
                <div style={{
                  width: '22px', height: '22px', borderRadius: '50%', flexShrink: 0,
                  background: 'rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', fontSize: '11px', fontWeight: 700, color: 'rgba(255,255,255,0.5)',
                }}>{i + 1}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                    <ShotTypePill type={shot.shot_type} />
                    <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>{shot.duration}s</span>
                    {shot.routed_model && <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.25)' }}>{shot.routed_model}</span>}
                    {shot.estimated_cost_usd && <span style={{ fontSize: '11px', color: '#30d158', marginLeft: 'auto' }}>${shot.estimated_cost_usd.toFixed(3)}</span>}
                  </div>
                  <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {shot.prompt || shot.description}
                  </p>
                  {shot.on_screen_text && (
                    <p style={{ fontSize: '11px', color: '#2997ff', marginTop: '3px' }}>"{shot.on_screen_text}"</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div>
          <p style={{ ...subText, marginBottom: '12px' }}>
            Gemini builds a shot list, assigns characters/locations, routes each shot to the best video model, and estimates per-shot cost.
          </p>
          <button className="btn-primary" onClick={run} disabled={loading} style={{ fontSize: '14px' }}>
            {loading ? 'Building storyboard...' : 'Generate Storyboard'}
          </button>
        </div>
      )}
      {error && <ErrorBanner msg={error} />}
    </div>
  );
}

// ─── Phase 4: Generation ──────────────────────────────────────────────────────

function GeneratePhase({ campaign, completedShots, totalShots, onReload }: {
  campaign: Campaign; completedShots: number; totalShots: number;
  onReload: () => Promise<Campaign>;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function run() {
    setLoading(true); setError('');
    try { await startGeneration(campaign.id); await onReload(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Failed to start'); }
    finally { setLoading(false); }
  }

  const pct = totalShots > 0 ? Math.round((completedShots / totalShots) * 100) : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '14px' }}>
      {campaign.status === 'generating' ? (
        <div style={{ background: 'rgba(255,159,10,0.07)', border: '1px solid rgba(255,159,10,0.25)', borderRadius: '10px', padding: '20px' }}>
          <p style={{ fontSize: '14px', fontWeight: 600, color: '#ff9f0a', marginBottom: '12px' }}>
            Generating shots in parallel... ({completedShots}/{totalShots})
          </p>
          <div style={{ background: 'rgba(255,255,255,0.1)', borderRadius: '999px', height: '6px', overflow: 'hidden' }}>
            <div style={{ height: '100%', background: '#ff9f0a', borderRadius: '999px', width: `${pct}%`, transition: 'width 0.5s' }} />
          </div>
          <p style={{ ...subText, marginTop: '8px' }}>Auto-refreshes every 8s</p>
        </div>
      ) : campaign.status === 'editing' || campaign.status === 'review' || campaign.status === 'completed' ? (
        <div style={{ background: 'rgba(48,209,88,0.07)', border: '1px solid rgba(48,209,88,0.2)', borderRadius: '10px', padding: '16px' }}>
          <p style={{ fontSize: '14px', fontWeight: 600, color: '#30d158' }}>All {totalShots} shots generated</p>
        </div>
      ) : (
        <div>
          <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '14px', marginBottom: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <p style={{ fontSize: '14px', color: '#e8e8ed', marginBottom: '4px' }}>{totalShots} shots queued</p>
                <p style={subText}>Each shot generates in parallel via the best available provider</p>
              </div>
              {campaign.total_cost_usd > 0 && (
                <p style={{ fontSize: '16px', fontWeight: 600, color: '#30d158' }}>${campaign.total_cost_usd.toFixed(3)}</p>
              )}
            </div>
          </div>
          <button className="btn-primary" onClick={run} disabled={loading || !campaign.storyboard} style={{ fontSize: '14px' }}>
            {loading ? 'Starting...' : 'Start Generation'}
          </button>
          {!campaign.storyboard && <p style={{ ...subText, marginTop: '8px' }}>Complete storyboard first</p>}
        </div>
      )}
      {error && <ErrorBanner msg={error} />}
    </div>
  );
}

// ─── Phase 5: Edit ────────────────────────────────────────────────────────────

function EditPhase({ campaign, onReload }: { campaign: Campaign; onReload: () => Promise<Campaign> }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [colorGrade, setColorGrade] = useState('cinematic');
  const [musicMood, setMusicMood] = useState('motivational');

  async function run() {
    setLoading(true); setError('');
    try { await runEditing(campaign.id, colorGrade, musicMood); await onReload(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  const done = campaign.status === 'review' || campaign.status === 'completed';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '14px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <div>
          <label style={labelStyle}>Color grade</label>
          <select value={colorGrade} onChange={e => setColorGrade(e.target.value)}
            className="input" style={{ fontSize: '14px', padding: '8px 12px' }}>
            {['cinematic', 'warm', 'cool', 'vivid', 'none'].map(g => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Music mood (Pixabay CC0)</label>
          <select value={musicMood} onChange={e => setMusicMood(e.target.value)}
            className="input" style={{ fontSize: '14px', padding: '8px 12px' }}>
            {['motivational', 'upbeat', 'energetic', 'calm', 'dramatic', 'corporate', 'inspiring'].map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      </div>
      <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '12px 14px' }}>
        <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)' }}>
          Pipeline: stitch shots → {colorGrade} color grade → filler-word cuts (Whisper) → LUFS audio normalization → export 9:16 + 1:1 + 16:9
        </p>
      </div>
      {done ? (
        <div style={{ background: 'rgba(48,209,88,0.07)', border: '1px solid rgba(48,209,88,0.2)', borderRadius: '10px', padding: '14px' }}>
          <p style={{ fontSize: '14px', fontWeight: 600, color: '#30d158' }}>Auto-edit complete — see variations below</p>
          <button className="btn-secondary" style={{ marginTop: '10px', fontSize: '13px', padding: '6px 12px' }}
            onClick={run} disabled={loading}>{loading ? 'Re-editing...' : 'Re-edit'}</button>
        </div>
      ) : (
        <div>
          <button className="btn-primary" onClick={run}
            disabled={loading || (campaign.status !== 'editing' && campaign.status !== 'storyboarding')}
            style={{ fontSize: '14px' }}>
            {loading ? 'Editing...' : 'Run Auto-Edit'}
          </button>
          {campaign.status !== 'editing' && campaign.status !== 'storyboarding' && (
            <p style={{ ...subText, marginTop: '8px' }}>Complete generation first</p>
          )}
        </div>
      )}
      {error && <ErrorBanner msg={error} />}
    </div>
  );
}

// ─── Phase 6: Review ─────────────────────────────────────────────────────────

function ReviewPhase({ campaign, variations, onVariationsReload }: {
  campaign: Campaign; variations: any[]; onVariationsReload: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [plans, setPlans] = useState<any[]>([]);
  const [showPlanner, setShowPlanner] = useState(false);

  async function loadPlans() {
    try {
      const r = await planVariants(campaign.id, ['hook', 'character', 'style'], 2);
      setPlans(r.data?.plans || []);
    } catch {}
  }

  async function handleCreate(plan: any) {
    setLoading(true);
    try {
      await createVariation(campaign.id, { strategy: plan.strategy, label: plan.label, auto_generate: true });
      onVariationsReload();
    } catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={labelStyle}>{variations.length} variation{variations.length !== 1 ? 's' : ''}</span>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn-secondary" style={{ fontSize: '12px', padding: '6px 12px' }}
            onClick={() => { loadPlans(); setShowPlanner(s => !s); }}>
            {showPlanner ? 'Hide planner' : '+ Create variants'}
          </button>
          <button className="btn-secondary" style={{ fontSize: '12px', padding: '6px 12px' }}
            onClick={onVariationsReload}>Refresh</button>
        </div>
      </div>

      {showPlanner && (
        <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '14px' }}>
          <p style={{ ...labelStyle, marginBottom: '10px' }}>Variant strategies</p>
          {plans.length === 0
            ? <p style={subText}>Loading plans…</p>
            : plans.map((plan, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 12px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px', marginBottom: '6px',
              }}>
                <div>
                  <p style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8ed' }}>{plan.label}</p>
                  <p style={subText}>{plan.shots_to_regenerate}/{plan.total_shots} shots regenerated · ${plan.estimated_cost_usd?.toFixed(3)}</p>
                </div>
                <button className="btn-primary" style={{ fontSize: '12px', padding: '6px 12px' }}
                  onClick={() => handleCreate(plan)} disabled={loading}>Create</button>
              </div>
            ))
          }
        </div>
      )}

      <VariationGrid campaignId={campaign.id} variations={variations} onReload={onVariationsReload} />
      {error && <ErrorBanner msg={error} />}
    </div>
  );
}

// ─── Characters tab ───────────────────────────────────────────────────────────

function CharactersTab({ characters, onCreated }: { characters: Character[]; onCreated: (c: Character) => void }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [portrait, setPortrait] = useState<File | null>(null);

  async function handleCreate() {
    if (!name) return;
    setLoading(true); setError('');
    try {
      const r = await createCharacter({ name, description, portrait });
      onCreated(r.data as Character);
      setName(''); setDescription(''); setPortrait(null);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', alignItems: 'start' }}>
      {/* Add form */}
      <div className="card" style={{ padding: '20px' }}>
        <h3 style={{ ...sectionTitle, marginBottom: '16px' }}>Add Character</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={labelStyle}>Name</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Sarah — relatable mom"
              className="input" style={{ fontSize: '14px', padding: '9px 12px' }} />
          </div>
          <div>
            <label style={labelStyle}>Description</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)}
              placeholder="Age, look, clothing, personality — used for image-to-video consistency"
              rows={3} className="input" style={{ fontSize: '14px', padding: '9px 12px', resize: 'vertical' }} />
          </div>
          <div>
            <label style={labelStyle}>Portrait / reference image</label>
            <label style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              height: '80px', borderRadius: '10px', cursor: 'pointer',
              background: 'rgba(255,255,255,0.04)', border: '1px dashed rgba(255,255,255,0.15)',
            }}>
              <input type="file" accept="image/*" style={{ display: 'none' }}
                onChange={e => setPortrait(e.target.files?.[0] || null)} />
              {portrait
                ? <span style={{ fontSize: '13px', color: '#30d158' }}>{portrait.name}</span>
                : <span style={subText}>Click to upload (optional)</span>}
            </label>
          </div>
        </div>
        {error && <ErrorBanner msg={error} />}
        <button className="btn-primary" onClick={handleCreate} disabled={loading || !name}
          style={{ marginTop: '16px', fontSize: '14px' }}>
          {loading ? 'Adding...' : 'Add Character'}
        </button>
      </div>

      {/* List */}
      <div className="card" style={{ padding: '20px' }}>
        <h3 style={{ ...sectionTitle, marginBottom: '16px' }}>Characters ({characters.length})</h3>
        {characters.length === 0 ? (
          <p style={subText}>No characters yet. Add one to use in storyboarding for consistent faces across shots.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {characters.map(c => (
              <div key={c.id} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '12px 14px', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                {c.portrait_url ? (
                  <img src={`${API_HOST}${c.portrait_url}`} alt={c.name}
                    style={{ width: '44px', height: '44px', borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
                ) : (
                  <div style={{ width: '44px', height: '44px', borderRadius: '50%', background: 'rgba(255,255,255,0.1)', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '16px', color: 'rgba(255,255,255,0.3)' }}>?</div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: '14px', fontWeight: 600, color: '#e8e8ed', marginBottom: '3px' }}>{c.name}</p>
                  {c.description && <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.description}</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Locations tab ────────────────────────────────────────────────────────────

function LocationsTab({ sceneSets, onCreated }: { sceneSets: SceneSetting[]; onCreated: (s: SceneSetting) => void }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [locationType, setLocationType] = useState('indoor');
  const [refImage, setRefImage] = useState<File | null>(null);

  async function handleCreate() {
    if (!name) return;
    setLoading(true); setError('');
    try {
      const r = await createSceneSetting({ name, description, location_type: locationType, reference_image: refImage });
      onCreated(r.data as SceneSetting);
      setName(''); setDescription(''); setRefImage(null);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', alignItems: 'start' }}>
      {/* Add form */}
      <div className="card" style={{ padding: '20px' }}>
        <h3 style={{ ...sectionTitle, marginBottom: '16px' }}>Add Location</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={labelStyle}>Name</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Modern kitchen — bright + natural light"
              className="input" style={{ fontSize: '14px', padding: '9px 12px' }} />
          </div>
          <div>
            <label style={labelStyle}>Type</label>
            <select value={locationType} onChange={e => setLocationType(e.target.value)}
              className="input" style={{ fontSize: '14px', padding: '9px 12px' }}>
              {['indoor', 'outdoor', 'studio', 'urban', 'nature', 'virtual'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Description</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)}
              placeholder="Lighting, props, style details — used for visual consistency across shots"
              rows={3} className="input" style={{ fontSize: '14px', padding: '9px 12px', resize: 'vertical' }} />
          </div>
          <div>
            <label style={labelStyle}>Reference image (optional)</label>
            <label style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              height: '80px', borderRadius: '10px', cursor: 'pointer',
              background: 'rgba(255,255,255,0.04)', border: '1px dashed rgba(255,255,255,0.15)',
            }}>
              <input type="file" accept="image/*" style={{ display: 'none' }}
                onChange={e => setRefImage(e.target.files?.[0] || null)} />
              {refImage
                ? <span style={{ fontSize: '13px', color: '#30d158' }}>{refImage.name}</span>
                : <span style={subText}>Click to upload</span>}
            </label>
          </div>
        </div>
        {error && <ErrorBanner msg={error} />}
        <button className="btn-primary" onClick={handleCreate} disabled={loading || !name}
          style={{ marginTop: '16px', fontSize: '14px' }}>
          {loading ? 'Adding...' : 'Add Location'}
        </button>
      </div>

      {/* List */}
      <div className="card" style={{ padding: '20px' }}>
        <h3 style={{ ...sectionTitle, marginBottom: '16px' }}>Locations ({sceneSets.length})</h3>
        {sceneSets.length === 0 ? (
          <p style={subText}>No locations yet. Add settings to keep consistent visual environments across shots.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {sceneSets.map(s => (
              <div key={s.id} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '12px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <p style={{ fontSize: '14px', fontWeight: 600, color: '#e8e8ed' }}>{s.name}</p>
                  <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.35)', background: 'rgba(255,255,255,0.07)', padding: '2px 8px', borderRadius: '999px' }}>{s.location_type}</span>
                </div>
                {s.description && <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)' }}>{s.description}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── New Campaign Modal ───────────────────────────────────────────────────────

function NewCampaignModal({ onClose, onCreated }: {
  onClose: () => void; onCreated: (c: Campaign) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [vertical, setVertical] = useState('home_insurance');
  const [brief, setBrief] = useState('');
  const [refVideo, setRefVideo] = useState<File | null>(null);
  const [refImage, setRefImage] = useState<File | null>(null);

  async function handleCreate() {
    if (!name || !vertical) return;
    setLoading(true); setError('');
    try {
      const r = await createCampaign({ name, vertical, brief_text: brief, reference_video: refVideo, reference_image: refImage });
      onCreated(r.data as Campaign);
    } catch (e: any) { setError(e?.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, padding: '20px' }}>
      <div className="card" style={{ width: '100%', maxWidth: '500px', padding: '28px' }}>
        <h2 style={{ ...sectionTitle, fontSize: '18px', marginBottom: '20px' }}>New Campaign</h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={labelStyle}>Campaign name</label>
            <input value={name} onChange={e => setName(e.target.value)} autoFocus
              placeholder="Q2 Insurance — Urgency Hook Test"
              className="input" style={{ fontSize: '14px', padding: '9px 12px' }} />
          </div>
          <div>
            <label style={labelStyle}>Vertical</label>
            <select value={vertical} onChange={e => setVertical(e.target.value)}
              className="input" style={{ fontSize: '14px', padding: '9px 12px' }}>
              {VERTICALS.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Brief / idea</label>
            <textarea value={brief} onChange={e => setBrief(e.target.value)} rows={3}
              placeholder="What's the offer? Target emotion? Key benefit?"
              className="input" style={{ fontSize: '14px', padding: '9px 12px', resize: 'vertical' }} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <UploadBox label="Reference video (optional)" accept="video/*" file={refVideo} onChange={setRefVideo} />
            <UploadBox label="Reference image (optional)" accept="image/*" file={refImage} onChange={setRefImage} />
          </div>
        </div>

        {error && <ErrorBanner msg={error} />}

        <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
          <button className="btn-primary" onClick={handleCreate} disabled={loading || !name}
            style={{ flex: 1, fontSize: '14px' }}>
            {loading ? 'Creating...' : 'Create Campaign'}
          </button>
          <button className="btn-secondary" onClick={onClose} style={{ fontSize: '14px', padding: '10px 16px' }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Tiny helpers ─────────────────────────────────────────────────────────────

function StatusPill({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    draft:         ['rgba(255,255,255,0.12)', 'rgba(255,255,255,0.5)'],
    briefing:      ['rgba(10,132,255,0.15)', '#2997ff'],
    scripting:     ['rgba(94,92,230,0.15)', '#9d9bf5'],
    storyboarding: ['rgba(191,90,242,0.15)', '#da8fff'],
    generating:    ['rgba(255,159,10,0.15)', '#ff9f0a'],
    editing:       ['rgba(255,69,58,0.15)', '#ff6961'],
    review:        ['rgba(94,92,230,0.15)', '#9d9bf5'],
    completed:     ['rgba(48,209,88,0.15)', '#30d158'],
  };
  const [bg, color] = map[status] || ['rgba(255,255,255,0.08)', 'rgba(255,255,255,0.4)'];
  return (
    <span style={{ fontSize: '11px', fontWeight: 600, padding: '2px 8px', borderRadius: '999px', background: bg, color }}>
      {status}
    </span>
  );
}

function ShotTypePill({ type }: { type: string }) {
  const map: Record<string, string> = {
    hero: '#ff9f0a', spokesperson: '#2997ff', b_roll: 'rgba(255,255,255,0.4)', transition: 'rgba(255,255,255,0.3)',
  };
  return (
    <span style={{ fontSize: '11px', padding: '2px 7px', borderRadius: '999px', background: 'rgba(255,255,255,0.07)', color: map[type] || 'rgba(255,255,255,0.4)' }}>
      {type}
    </span>
  );
}

function CheckRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={onChange}
        style={{ accentColor: '#0071e3', width: '14px', height: '14px' }} />
      <span style={{ fontSize: '13px', color: '#e8e8ed' }}>{label}</span>
    </label>
  );
}

function UploadBox({ label, accept, file, onChange }: {
  label: string; accept: string; file: File | null; onChange: (f: File | null) => void;
}) {
  return (
    <div>
      <label style={{ ...labelStyle, marginBottom: '6px' }}>{label}</label>
      <label style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '64px', borderRadius: '10px', cursor: 'pointer',
        background: 'rgba(255,255,255,0.04)', border: '1px dashed rgba(255,255,255,0.15)',
      }}>
        <input type="file" accept={accept} style={{ display: 'none' }}
          onChange={e => onChange(e.target.files?.[0] || null)} />
        {file
          ? <span style={{ fontSize: '11px', color: '#30d158', padding: '0 8px', textAlign: 'center' }}>{file.name}</span>
          : <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.3)' }}>Click to upload</span>}
      </label>
    </div>
  );
}

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <div style={{ background: 'rgba(255,69,58,0.1)', border: '1px solid rgba(255,69,58,0.3)', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#ff6961' }}>
      {msg}
    </div>
  );
}
