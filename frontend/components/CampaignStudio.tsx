'use client';

import { useState, useEffect, useRef } from 'react';
import {
  createCampaign, getCampaign, runBriefing, runScripting, runStoryboarding,
  startGeneration, runEditing, listCharacters, listSceneSettings,
  createCharacter, createSceneSetting, listVariations, listCampaigns,
  planVariants, createVariation, API_HOST,
} from '../lib/api';
import { VERTICALS } from '../lib/verticals';
import VariationGrid from './VariationGrid';

// ─────────────────────────────────────── Types

interface Campaign {
  id: string;
  name: string;
  vertical: string;
  status: string;
  brief_text: string;
  analyzed_brief: Record<string, any> | null;
  script: string | null;
  storyboard: any[] | null;
  shots: any[];
  total_cost_usd: number;
  created_at: string;
}

interface Character { id: string; name: string; description: string; portrait_url: string | null; consistency_prompt: string | null; }
interface SceneSetting { id: string; name: string; description: string; location_type: string; reference_image_url: string | null; }

const STEPS = ['brief', 'script', 'storyboard', 'generate', 'edit', 'review'] as const;
type Step = typeof STEPS[number];

const STEP_LABELS: Record<Step, string> = {
  brief: 'Brief',
  script: 'Script',
  storyboard: 'Storyboard',
  generate: 'Generate',
  edit: 'Edit',
  review: 'Review',
};

const STATUS_TO_STEP: Record<string, Step> = {
  draft: 'brief',
  briefing: 'script',
  scripting: 'storyboard',
  storyboarding: 'generate',
  generating: 'generate',
  editing: 'edit',
  review: 'review',
  completed: 'review',
};

// ─────────────────────────────────────── Component

export default function CampaignStudio() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [step, setStep] = useState<Step>('brief');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pollTimer, setPollTimer] = useState<NodeJS.Timeout | null>(null);

  // Characters + settings
  const [characters, setCharacters] = useState<Character[]>([]);
  const [sceneSets, setSceneSets] = useState<SceneSetting[]>([]);
  const [selectedCharIds, setSelectedCharIds] = useState<string[]>([]);
  const [selectedSettingIds, setSelectedSettingIds] = useState<string[]>([]);

  // New campaign form
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newVertical, setNewVertical] = useState('home_insurance');
  const [newBrief, setNewBrief] = useState('');
  const [refVideo, setRefVideo] = useState<File | null>(null);
  const [refImage, setRefImage] = useState<File | null>(null);

  // Scripting
  const [targetDuration, setTargetDuration] = useState(30);
  const [extraInstructions, setExtraInstructions] = useState('');

  // Edit
  const [colorGrade, setColorGrade] = useState('cinematic');
  const [musicMood, setMusicMood] = useState('motivational');

  // Variations
  const [variations, setVariations] = useState<any[]>([]);
  const [variantPlans, setVariantPlans] = useState<any[]>([]);
  const [showVariantPlanner, setShowVariantPlanner] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    loadCampaigns();
    loadCharactersAndSettings();
  }, []);

  useEffect(() => {
    if (selected) {
      setStep(STATUS_TO_STEP[selected.status] || 'brief');
    }
  }, [selected]);

  // Poll for generation progress
  useEffect(() => {
    if (selected?.status === 'generating') {
      const timer = setInterval(async () => {
        try {
          const r = await getCampaign(selected.id);
          const updated = r.data as Campaign;
          setSelected(updated);
          if (updated.status !== 'generating') {
            clearInterval(timer);
          }
        } catch {}
      }, 8000);
      setPollTimer(timer);
      return () => clearInterval(timer);
    }
  }, [selected?.status]);

  async function loadCampaigns() {
    try {
      const r = await listCampaigns();
      setCampaigns(r.data?.campaigns || []);
    } catch {}
  }

  async function loadCharactersAndSettings() {
    try {
      const [cRes, sRes] = await Promise.all([listCharacters(), listSceneSettings()]);
      setCharacters(cRes.data?.characters || []);
      setSceneSets(sRes.data?.settings || []);
    } catch {}
  }

  async function handleCreate() {
    if (!newName || !newVertical) return;
    setLoading(true);
    setError('');
    try {
      const r = await createCampaign({
        name: newName, vertical: newVertical,
        brief_text: newBrief,
        reference_video: refVideo,
        reference_image: refImage,
      });
      const campaign = r.data as Campaign;
      setCampaigns(prev => [campaign, ...prev]);
      setSelected(campaign);
      setShowNewForm(false);
      setNewName(''); setNewBrief(''); setRefVideo(null); setRefImage(null);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to create campaign');
    } finally {
      setLoading(false);
    }
  }

  async function handleBriefing() {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      await runBriefing(selected.id);
      const r = await getCampaign(selected.id);
      setSelected(r.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Briefing failed');
    } finally { setLoading(false); }
  }

  async function handleScripting() {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      await runScripting(selected.id, targetDuration, extraInstructions);
      const r = await getCampaign(selected.id);
      setSelected(r.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Scripting failed');
    } finally { setLoading(false); }
  }

  async function handleStoryboarding() {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      await runStoryboarding(selected.id, selectedCharIds, selectedSettingIds, targetDuration);
      const r = await getCampaign(selected.id);
      setSelected(r.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Storyboarding failed');
    } finally { setLoading(false); }
  }

  async function handleGenerate() {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      await startGeneration(selected.id);
      const r = await getCampaign(selected.id);
      setSelected(r.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Generation failed to start');
    } finally { setLoading(false); }
  }

  async function handleEdit() {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      await runEditing(selected.id, colorGrade, musicMood);
      const r = await getCampaign(selected.id);
      setSelected(r.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Editing failed');
    } finally { setLoading(false); }
  }

  async function loadVariations() {
    if (!selected) return;
    try {
      const r = await listVariations(selected.id);
      setVariations(r.data?.variations || []);
    } catch {}
  }

  async function loadVariantPlans() {
    if (!selected) return;
    const r = await planVariants(selected.id, ['hook', 'character', 'style'], 2);
    setVariantPlans(r.data?.plans || []);
  }

  async function handleCreateVariant(plan: any) {
    if (!selected) return;
    setLoading(true);
    try {
      await createVariation(selected.id, {
        strategy: plan.strategy,
        label: plan.label,
        auto_generate: true,
      });
      await loadVariations();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Variant creation failed');
    } finally { setLoading(false); }
  }

  useEffect(() => {
    if (selected && step === 'review') {
      loadVariations();
    }
  }, [step, selected?.id]);

  const completedShots = selected?.shots?.filter((s: any) => s.status === 'completed').length || 0;
  const totalShots = selected?.shots?.length || 0;

  return (
    <div className="h-screen bg-gray-950 text-white flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-800 px-6 py-4 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-violet-500 rounded-lg flex items-center justify-center text-sm font-bold">C</div>
          <h1 className="text-lg font-semibold">Campaign Studio</h1>
        </div>
        <button
          onClick={() => setShowNewForm(true)}
          className="px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm font-medium transition-colors"
        >
          + New Campaign
        </button>
      </div>

      <div className="flex h-[calc(100vh-65px)]">

        {/* Sidebar — campaign list */}
        <div className="w-64 border-r border-gray-800 overflow-y-auto flex-shrink-0">
          {campaigns.length === 0 ? (
            <div className="p-4 text-gray-500 text-sm">No campaigns yet</div>
          ) : (
            campaigns.map(c => (
              <button
                key={c.id}
                onClick={() => setSelected(c)}
                className={`w-full text-left px-4 py-3 border-b border-gray-800 hover:bg-gray-900 transition-colors ${selected?.id === c.id ? 'bg-gray-900 border-l-2 border-l-violet-500' : ''}`}
              >
                <div className="text-sm font-medium truncate">{c.name}</div>
                <div className="flex items-center gap-2 mt-1">
                  <StatusBadge status={c.status} />
                  <span className="text-xs text-gray-500">{c.vertical}</span>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Main area */}
        <div className="flex-1 overflow-y-auto">
          {!selected ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-500">
              <div className="text-5xl mb-4">🎬</div>
              <p className="text-lg">Select or create a campaign</p>
              <button
                onClick={() => setShowNewForm(true)}
                className="mt-4 px-6 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-white text-sm font-medium"
              >
                Create your first campaign
              </button>
            </div>
          ) : (
            <div className="p-6 max-w-4xl mx-auto">

              {/* Campaign header */}
              <div className="mb-6">
                <h2 className="text-xl font-bold">{selected.name}</h2>
                <div className="flex items-center gap-3 mt-1">
                  <StatusBadge status={selected.status} />
                  <span className="text-sm text-gray-400">{selected.vertical}</span>
                  {selected.total_cost_usd > 0 && (
                    <span className="text-sm text-green-400">${selected.total_cost_usd.toFixed(3)} spent</span>
                  )}
                </div>
              </div>

              {/* Step indicator */}
              <StepIndicator currentStep={step} status={selected.status} />

              {error && (
                <div className="mt-4 p-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
                  {error}
                </div>
              )}

              {/* Step content */}
              <div className="mt-6">

                {/* ── BRIEF ── */}
                {step === 'brief' && (
                  <div className="space-y-4">
                    <div className="p-4 bg-gray-900 rounded-xl border border-gray-800">
                      <h3 className="font-semibold mb-2">Brief</h3>
                      <p className="text-gray-400 text-sm">{selected.brief_text || '(no brief text)'}</p>
                    </div>
                    {selected.analyzed_brief ? (
                      <div className="p-4 bg-gray-900 rounded-xl border border-gray-800">
                        <h3 className="font-semibold mb-3">Analyzed Brief</h3>
                        <BriefDisplay brief={selected.analyzed_brief} />
                        <button
                          onClick={() => setStep('script')}
                          className="mt-4 px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm font-medium"
                        >
                          Next: Generate Script →
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={handleBriefing}
                        disabled={loading}
                        className="px-6 py-3 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-xl font-medium"
                      >
                        {loading ? 'Analyzing reference...' : 'Analyze Brief →'}
                      </button>
                    )}
                  </div>
                )}

                {/* ── SCRIPT ── */}
                {step === 'script' && (
                  <div className="space-y-4">
                    <div className="flex gap-4 items-end">
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Target duration</label>
                        <select
                          value={targetDuration}
                          onChange={e => setTargetDuration(+e.target.value)}
                          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                        >
                          {[15, 20, 30, 45, 60].map(d => (
                            <option key={d} value={d}>{d}s</option>
                          ))}
                        </select>
                      </div>
                      <div className="flex-1">
                        <label className="block text-sm text-gray-400 mb-1">Extra instructions</label>
                        <input
                          type="text"
                          value={extraInstructions}
                          onChange={e => setExtraInstructions(e.target.value)}
                          placeholder="e.g. Focus on testimonial hook"
                          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                    </div>
                    {selected.script ? (
                      <div className="p-4 bg-gray-900 rounded-xl border border-gray-800">
                        <div className="flex items-center justify-between mb-2">
                          <h3 className="font-semibold">Generated Script</h3>
                          <button
                            onClick={handleScripting}
                            className="text-xs text-violet-400 hover:text-violet-300"
                          >Regenerate</button>
                        </div>
                        <pre className="text-sm text-gray-300 whitespace-pre-wrap">{selected.script}</pre>
                        <button
                          onClick={() => setStep('storyboard')}
                          className="mt-4 px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm font-medium"
                        >
                          Next: Storyboard →
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={handleScripting}
                        disabled={loading}
                        className="px-6 py-3 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-xl font-medium"
                      >
                        {loading ? 'Writing script...' : 'Generate Script →'}
                      </button>
                    )}
                  </div>
                )}

                {/* ── STORYBOARD ── */}
                {step === 'storyboard' && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm text-gray-400 mb-2">Characters</label>
                        <div className="space-y-2 max-h-40 overflow-y-auto">
                          {characters.map(c => (
                            <label key={c.id} className="flex items-center gap-2 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={selectedCharIds.includes(c.id)}
                                onChange={e => {
                                  if (e.target.checked) setSelectedCharIds(p => [...p, c.id]);
                                  else setSelectedCharIds(p => p.filter(x => x !== c.id));
                                }}
                                className="accent-violet-500"
                              />
                              <span className="text-sm">{c.name}</span>
                            </label>
                          ))}
                          {characters.length === 0 && <p className="text-xs text-gray-500">No characters yet</p>}
                        </div>
                      </div>
                      <div>
                        <label className="block text-sm text-gray-400 mb-2">Settings</label>
                        <div className="space-y-2 max-h-40 overflow-y-auto">
                          {sceneSets.map(s => (
                            <label key={s.id} className="flex items-center gap-2 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={selectedSettingIds.includes(s.id)}
                                onChange={e => {
                                  if (e.target.checked) setSelectedSettingIds(p => [...p, s.id]);
                                  else setSelectedSettingIds(p => p.filter(x => x !== s.id));
                                }}
                                className="accent-violet-500"
                              />
                              <span className="text-sm">{s.name}</span>
                            </label>
                          ))}
                          {sceneSets.length === 0 && <p className="text-xs text-gray-500">No settings yet</p>}
                        </div>
                      </div>
                    </div>

                    {selected.storyboard ? (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <h3 className="font-semibold">Shot List ({selected.storyboard.length} shots)</h3>
                          <button onClick={handleStoryboarding} className="text-xs text-violet-400 hover:text-violet-300">Regenerate</button>
                        </div>
                        <ShotList shots={selected.storyboard} />
                        <button
                          onClick={() => setStep('generate')}
                          className="px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm font-medium"
                        >
                          Next: Generate Videos →
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={handleStoryboarding}
                        disabled={loading}
                        className="px-6 py-3 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-xl font-medium"
                      >
                        {loading ? 'Building storyboard...' : 'Generate Storyboard →'}
                      </button>
                    )}
                  </div>
                )}

                {/* ── GENERATE ── */}
                {step === 'generate' && (
                  <div className="space-y-4">
                    {selected.status === 'generating' ? (
                      <div className="p-6 bg-gray-900 rounded-xl border border-gray-800 text-center">
                        <div className="text-3xl mb-3 animate-pulse">⚙️</div>
                        <h3 className="font-semibold mb-1">Generating shots...</h3>
                        <div className="mt-4 bg-gray-800 rounded-full h-2 overflow-hidden">
                          <div
                            className="bg-violet-500 h-full transition-all duration-500"
                            style={{ width: totalShots ? `${(completedShots / totalShots) * 100}%` : '0%' }}
                          />
                        </div>
                        <p className="text-sm text-gray-400 mt-2">{completedShots} / {totalShots} shots complete</p>
                        <p className="text-xs text-gray-500 mt-1">Polling every 8s…</p>
                      </div>
                    ) : selected.status === 'editing' || selected.status === 'review' || selected.status === 'completed' ? (
                      <div className="p-4 bg-green-900/30 border border-green-700 rounded-xl">
                        <p className="text-green-300 font-medium">All {totalShots} shots generated ✓</p>
                        <button onClick={() => setStep('edit')} className="mt-3 px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm">Next: Edit →</button>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <div className="p-4 bg-gray-900 rounded-xl border border-gray-800">
                          <p className="text-sm text-gray-300 mb-2">{totalShots} shots ready to generate</p>
                          <p className="text-xs text-gray-500">Estimated cost: ${selected.total_cost_usd?.toFixed(3) || '...'}</p>
                        </div>
                        <button
                          onClick={handleGenerate}
                          disabled={loading}
                          className="px-6 py-3 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-xl font-medium"
                        >
                          {loading ? 'Starting...' : 'Start Generation →'}
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {/* ── EDIT ── */}
                {step === 'edit' && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Color grade</label>
                        <select
                          value={colorGrade}
                          onChange={e => setColorGrade(e.target.value)}
                          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                        >
                          {['cinematic', 'warm', 'cool', 'vivid', 'none'].map(g => (
                            <option key={g} value={g}>{g}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Music mood</label>
                        <select
                          value={musicMood}
                          onChange={e => setMusicMood(e.target.value)}
                          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                        >
                          {['motivational', 'upbeat', 'energetic', 'calm', 'dramatic', 'corporate', 'inspiring'].map(m => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    {selected.status === 'review' || selected.status === 'completed' ? (
                      <div className="p-4 bg-green-900/30 border border-green-700 rounded-xl">
                        <p className="text-green-300 font-medium">Editing complete ✓</p>
                        <button onClick={() => setStep('review')} className="mt-3 px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm">Review Variations →</button>
                      </div>
                    ) : (
                      <button
                        onClick={handleEdit}
                        disabled={loading}
                        className="px-6 py-3 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-xl font-medium"
                      >
                        {loading ? 'Editing...' : 'Run Auto-Edit →'}
                      </button>
                    )}
                  </div>
                )}

                {/* ── REVIEW ── */}
                {step === 'review' && (
                  <div className="space-y-6">
                    <div className="flex items-center justify-between">
                      <h3 className="font-semibold">Variations ({variations.length})</h3>
                      <div className="flex gap-2">
                        <button
                          onClick={() => { loadVariantPlans(); setShowVariantPlanner(true); }}
                          className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs"
                        >
                          + Create Variants
                        </button>
                        <button onClick={loadVariations} className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs">
                          Refresh
                        </button>
                      </div>
                    </div>

                    {showVariantPlanner && (
                      <VariantPlanner
                        plans={variantPlans}
                        onCreateVariant={handleCreateVariant}
                        onClose={() => setShowVariantPlanner(false)}
                        loading={loading}
                      />
                    )}

                    <VariationGrid
                      campaignId={selected.id}
                      variations={variations}
                      onReload={loadVariations}
                    />
                  </div>
                )}

              </div>
            </div>
          )}
        </div>
      </div>

      {/* New Campaign Modal */}
      {showNewForm && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-lg mx-4">
            <h2 className="text-lg font-semibold mb-4">New Campaign</h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Campaign name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  placeholder="Q2 Insurance — Urgency Hook Test"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Vertical</label>
                <select
                  value={newVertical}
                  onChange={e => setNewVertical(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                >
                  {VERTICALS.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Brief / idea</label>
                <textarea
                  value={newBrief}
                  onChange={e => setNewBrief(e.target.value)}
                  rows={3}
                  placeholder="What's the offer? Target emotion? Key benefit?"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm resize-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <FileUploadField
                  label="Reference video (optional)"
                  accept="video/*"
                  onChange={setRefVideo}
                  current={refVideo}
                />
                <FileUploadField
                  label="Reference image (optional)"
                  accept="image/*"
                  onChange={setRefImage}
                  current={refImage}
                />
              </div>
            </div>

            {error && <p className="mt-3 text-red-400 text-sm">{error}</p>}

            <div className="flex gap-3 mt-6">
              <button
                onClick={handleCreate}
                disabled={loading || !newName}
                className="flex-1 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg font-medium text-sm"
              >
                {loading ? 'Creating...' : 'Create Campaign'}
              </button>
              <button
                onClick={() => { setShowNewForm(false); setError(''); }}
                className="px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────── Sub-components

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: 'bg-gray-700 text-gray-300',
    briefing: 'bg-blue-900 text-blue-300',
    scripting: 'bg-indigo-900 text-indigo-300',
    storyboarding: 'bg-purple-900 text-purple-300',
    generating: 'bg-yellow-900 text-yellow-300',
    editing: 'bg-orange-900 text-orange-300',
    review: 'bg-violet-900 text-violet-300',
    completed: 'bg-green-900 text-green-300',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-800 text-gray-400'}`}>
      {status}
    </span>
  );
}

function StepIndicator({ currentStep, status }: { currentStep: Step; status: string }) {
  const currentIdx = STEPS.indexOf(currentStep);
  return (
    <div className="flex items-center gap-1">
      {STEPS.map((s, i) => (
        <div key={s} className="flex items-center">
          <div className={`px-3 py-1 rounded-full text-xs font-medium ${
            i < currentIdx ? 'bg-green-900 text-green-300' :
            i === currentIdx ? 'bg-violet-600 text-white' :
            'bg-gray-800 text-gray-500'
          }`}>
            {STEP_LABELS[s]}
          </div>
          {i < STEPS.length - 1 && <div className="w-4 h-px bg-gray-700 mx-1" />}
        </div>
      ))}
    </div>
  );
}

function BriefDisplay({ brief }: { brief: Record<string, any> }) {
  const fields = [
    ['Hook style', brief.hook_style],
    ['Ad arc', brief.ad_arc],
    ['Visual rhythm', brief.visual_rhythm],
    ['Color palette', brief.color_palette],
    ['Camera style', brief.camera_style],
    ['CTA style', brief.cta_style],
  ].filter(([, v]) => v);
  return (
    <div className="grid grid-cols-2 gap-3">
      {fields.map(([label, value]) => (
        <div key={label as string}>
          <p className="text-xs text-gray-500">{label as string}</p>
          <p className="text-sm text-gray-200">{value as string}</p>
        </div>
      ))}
      {brief.key_insights?.length > 0 && (
        <div className="col-span-2">
          <p className="text-xs text-gray-500 mb-1">Key insights</p>
          <ul className="text-sm text-gray-300 list-disc list-inside space-y-1">
            {brief.key_insights.map((i: string, idx: number) => <li key={idx}>{i}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function ShotList({ shots }: { shots: any[] }) {
  return (
    <div className="space-y-2">
      {shots.map((shot, i) => (
        <div key={i} className="flex items-start gap-3 p-3 bg-gray-900 rounded-lg border border-gray-800">
          <div className="w-6 h-6 bg-gray-700 rounded-full flex items-center justify-center text-xs flex-shrink-0">{i + 1}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <ShotTypeBadge type={shot.shot_type} />
              <span className="text-xs text-gray-500">{shot.duration}s</span>
              {shot.routed_model && <span className="text-xs text-gray-600">{shot.routed_model}</span>}
            </div>
            <p className="text-xs text-gray-400 truncate">{shot.prompt || shot.description}</p>
            {shot.on_screen_text && <p className="text-xs text-violet-400 mt-0.5">"{shot.on_screen_text}"</p>}
          </div>
          {shot.estimated_cost_usd && (
            <span className="text-xs text-gray-600 flex-shrink-0">${shot.estimated_cost_usd.toFixed(3)}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function ShotTypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    hero: 'bg-yellow-900 text-yellow-300',
    spokesperson: 'bg-blue-900 text-blue-300',
    b_roll: 'bg-gray-700 text-gray-300',
    transition: 'bg-gray-800 text-gray-400',
  };
  return <span className={`px-1.5 py-0.5 rounded text-xs ${colors[type] || 'bg-gray-800 text-gray-400'}`}>{type}</span>;
}

function FileUploadField({ label, accept, onChange, current }: {
  label: string; accept: string; onChange: (f: File | null) => void; current: File | null;
}) {
  return (
    <div>
      <label className="block text-sm text-gray-400 mb-1">{label}</label>
      <label className="flex items-center justify-center h-16 bg-gray-800 border border-dashed border-gray-600 rounded-lg cursor-pointer hover:border-gray-500 transition-colors">
        <input type="file" accept={accept} className="hidden" onChange={e => onChange(e.target.files?.[0] || null)} />
        {current ? (
          <span className="text-xs text-violet-400 truncate px-2">{current.name}</span>
        ) : (
          <span className="text-xs text-gray-500">Click to upload</span>
        )}
      </label>
    </div>
  );
}

function VariantPlanner({ plans, onCreateVariant, onClose, loading }: {
  plans: any[];
  onCreateVariant: (p: any) => void;
  onClose: () => void;
  loading: boolean;
}) {
  return (
    <div className="p-4 bg-gray-900 rounded-xl border border-violet-800">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-medium text-sm">Variant Plans</h4>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xs">✕</button>
      </div>
      {plans.length === 0 ? (
        <p className="text-xs text-gray-500">Loading plans...</p>
      ) : (
        <div className="space-y-2">
          {plans.map((plan, i) => (
            <div key={i} className="flex items-center justify-between p-2 bg-gray-800 rounded-lg">
              <div>
                <p className="text-sm font-medium">{plan.label}</p>
                <p className="text-xs text-gray-500">{plan.shots_to_regenerate} / {plan.total_shots} shots regenerated · ${plan.estimated_cost_usd.toFixed(3)}</p>
              </div>
              <button
                onClick={() => onCreateVariant(plan)}
                disabled={loading}
                className="px-3 py-1 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 rounded text-xs"
              >
                Create
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
