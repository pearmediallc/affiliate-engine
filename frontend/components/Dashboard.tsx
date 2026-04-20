'use client';

import { useState } from 'react';
import { generateImages } from '@/lib/api';
import ImageGenerator from './ImageGenerator';
import ImageGallery from './ImageGallery';
import Analytics from './Analytics';
import ScriptToAudio from './ScriptToAudio';
import ScriptGenerator from './ScriptGenerator';
import VideoHookAnalyzer from './VideoHookAnalyzer';
import VideoScriptAnalyzer from './VideoScriptAnalyzer';
import VideoDownloader from './VideoDownloader';
import AdminPanel from './AdminPanel';
import UGCVideoStudio from './UGCVideoStudio';
import { useAuth } from '@/lib/auth';

interface Template {
  [key: string]: unknown;
}

interface AnalyticsData {
  [key: string]: unknown;
}

const navGroups = [
  {
    label: 'CREATIVE',
    items: [
      { id: 'generate', label: 'Generate Images', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      )},
      { id: 'gallery', label: 'Gallery', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="M21 15l-5-5L5 21" />
        </svg>
      ), countKey: 'gallery' as const },
      { id: 'scripts', label: 'Script Generator', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <path d="M14 2v6h6" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <line x1="10" y1="9" x2="8" y2="9" />
        </svg>
      )},
      { id: 'script-to-audio', label: 'Script to Audio', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
          <path d="M19 10v2a7 7 0 01-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
      )},
      { id: 'ugc-videos', label: 'UGC Videos', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="2" width="20" height="20" rx="2" /><path d="M10 8l6 4-6 4V8z" />
        </svg>
      )},
    ],
  },
  {
    label: 'ANALYSIS',
    items: [
      { id: 'video-hook', label: 'Hook Analyzer', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polygon points="10 8 16 12 10 16 10 8" />
        </svg>
      )},
      { id: 'video-script', label: 'Transcript Analyzer', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        </svg>
      )},
      { id: 'video-downloader', label: 'Video Downloader', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
      )},
    ],
  },
  {
    label: 'INSIGHTS',
    items: [
      { id: 'analytics', label: 'Analytics', icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
      )},
    ],
  },
];

const pageMeta: Record<string, { title: string; description: string }> = {
  generate: { title: 'Generate Images', description: 'Create high-performing ad images for affiliate campaigns' },
  gallery: { title: 'Gallery', description: 'Browse and manage your generated images' },
  scripts: { title: 'Script Generator', description: 'Generate persuasive ad scripts for your campaigns' },
  'script-to-audio': { title: 'Script to Audio', description: 'Convert scripts into professional voiceovers' },
  'ugc-videos': { title: 'UGC Videos', description: 'Create TikTok-style UGC videos with AI avatars' },
  'video-hook': { title: 'Hook Analyzer', description: 'Analyze video hooks for engagement patterns' },
  'video-script': { title: 'Transcript Analyzer', description: 'Extract insights from video transcripts' },
  'video-downloader': { title: 'Video Downloader', description: 'Download videos for analysis and reference' },
  analytics: { title: 'Analytics', description: 'Track performance across your campaigns' },
  admin: { title: 'Admin Panel', description: 'Manage users, review feedback, and approve AI suggestions' },
};

export default function Dashboard({ templates, analytics, error, vertical = 'home_insurance', onVerticalChange }: { templates?: Template[]; analytics?: AnalyticsData | null; error?: string; vertical?: string; onVerticalChange?: (v: string) => void }) {
  const { user, logout, hasPermission } = useAuth();
  const [activeTab, setActiveTab] = useState('generate');
  const [generatedImages, setGeneratedImages] = useState([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationError, setGenerationError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleGenerateImages = async (
    templateId: string,
    context?: string,
    numVariations: number = 5,
    useAffiliateAngles: boolean = true,
    affiliateAngle: string = 'benefit',
    useGemmaVariations: boolean = false,
    referenceImageBase64?: string,
    referenceText?: string,
    verticalOverride?: string,
    style: string = 'professional_photography',
    textMode: string = 'none',
    postProcess: string = 'editorial',
    headlineText?: string,
    subheadingText?: string,
    ctaText?: string,
  ) => {
    try {
      setIsGenerating(true);
      setGenerationError('');
      const result = await generateImages(
        templateId,
        context,
        numVariations,
        useAffiliateAngles,
        affiliateAngle,
        useGemmaVariations,
        referenceImageBase64,
        referenceText,
        verticalOverride || vertical,
        style,
        textMode,
        postProcess,
        headlineText,
        subheadingText,
        ctaText,
      );

      if (result.data && result.data.images) {
        setGeneratedImages(result.data.images);
        setActiveTab('gallery');
      }
    } catch (err) {
      console.error('Generation error:', err);
      setGenerationError('Failed to generate images. Please try again.');
    } finally {
      setIsGenerating(false);
    }
  };

  const currentPage = pageMeta[activeTab] || { title: activeTab, description: '' };

  return (
    <div className="flex min-h-screen" style={{ backgroundColor: '#f5f5f7', fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, sans-serif' }}>
      {/* Mobile hamburger button */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="lg:hidden fixed top-4 left-4 z-[60] p-2 rounded-lg"
        style={{ background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(10px)' }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5">
          {sidebarOpen ? (
            <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" />
          ) : (
            <><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></>
          )}
        </svg>
      </button>

      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="sidebar-backdrop lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed left-0 top-0 h-screen w-[260px] z-50 flex-col ${sidebarOpen ? 'flex' : 'hidden lg:flex'}`}
        style={{
          background: 'rgba(0,0,0,0.8)',
          backdropFilter: 'saturate(180%) blur(20px)',
          WebkitBackdropFilter: 'saturate(180%) blur(20px)',
        }}
      >
        {/* Logo / Brand */}
        <div className="px-6 py-8">
          <h1 style={{ fontSize: '21px', fontWeight: 600, color: '#fff', letterSpacing: '0.231px', margin: 0 }}>
            Affiliate Engine
          </h1>
          <p style={{ fontSize: '14px', color: 'rgba(255,255,255,0.5)', marginTop: '4px', margin: '4px 0 0 0' }}>
            AI Creative Platform
          </p>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 overflow-y-auto">
          {[...navGroups, ...(hasPermission('admin_panel') ? [{
            label: 'ADMIN',
            items: [{ id: 'admin', label: 'Admin Panel', icon: (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
              </svg>
            )}],
          }] : [])].map((group) => (
            <div key={group.label} className="mb-6">
              <div
                className="px-4 mb-2"
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'rgba(255,255,255,0.35)',
                  letterSpacing: '0.8px',
                  textTransform: 'uppercase' as const,
                }}
              >
                {group.label}
              </div>
              {group.items.map((item) => {
                const isActive = activeTab === item.id;
                const showCount = 'countKey' in item && item.countKey === 'gallery';
                return (
                  <button
                    key={item.id}
                    onClick={() => { setActiveTab(item.id); setSidebarOpen(false); }}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg mb-0.5 text-left transition-all ${
                      isActive
                        ? 'text-white'
                        : 'text-white/70 hover:bg-white/5 hover:text-white'
                    }`}
                    style={{
                      fontSize: '14px',
                      letterSpacing: '-0.224px',
                      fontWeight: isActive ? 600 : 400,
                      background: isActive ? 'rgba(255,255,255,0.1)' : 'transparent',
                      borderLeft: isActive ? '3px solid #0071e3' : '3px solid transparent',
                      paddingLeft: isActive ? '13px' : '13px',
                    }}
                  >
                    {item.icon}
                    <span>
                      {item.label}
                      {showCount ? ` (${generatedImages.length})` : ''}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Vertical Selector */}
        <div className="px-4 py-4" style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }}>
          <label
            style={{
              fontSize: '11px',
              fontWeight: 600,
              color: 'rgba(255,255,255,0.35)',
              letterSpacing: '0.8px',
              textTransform: 'uppercase' as const,
              display: 'block',
              marginBottom: '8px',
              paddingLeft: '4px',
            }}
          >
            Vertical
          </label>
          <select
            value={vertical}
            onChange={(e) => onVerticalChange?.(e.target.value)}
            style={{
              background: 'rgba(255,255,255,0.1)',
              color: 'white',
              border: '1px solid rgba(255,255,255,0.15)',
              borderRadius: '8px',
              padding: '8px 12px',
              fontSize: '14px',
              width: '100%',
              outline: 'none',
              appearance: 'none' as const,
              WebkitAppearance: 'none' as const,
              cursor: 'pointer',
              backgroundImage: `url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l4 4 4-4' stroke='rgba(255,255,255,0.5)' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")`,
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 12px center',
              paddingRight: '32px',
            }}
          >
            <optgroup label="Insurance">
              <option value="home_insurance">Home Insurance</option>
              <option value="concealed_carry">Concealed Carry Permits</option>
              <option value="health_insurance">Health Insurance</option>
              <option value="life_insurance">Life Insurance</option>
              <option value="auto_insurance">Auto Insurance</option>
              <option value="medicare">Medicare Supplements</option>
            </optgroup>
            <optgroup label="Health & Wellness">
              <option value="nutra">Weight Loss Supplements</option>
              <option value="blood_sugar">Blood Sugar Management</option>
              <option value="cbd">CBD/Hemp Products</option>
              <option value="ed">ED Enhancement</option>
            </optgroup>
            <optgroup label="Finance & Home">
              <option value="refinance">Mortgage Refinance</option>
              <option value="home_improvement">Home Improvement</option>
              <option value="wifi">WiFi/Mesh Routers</option>
            </optgroup>
            <optgroup label="Opportunity">
              <option value="bizop">Work-From-Home/Bizop</option>
            </optgroup>
          </select>
        </div>

        {/* User Info */}
        {user && (
          <div className="px-4 py-4" style={{ borderTop: '1px solid rgba(255,255,255,0.1)' }}>
            <div className="flex items-center gap-3">
              <div style={{
                width: '32px', height: '32px', borderRadius: '50%',
                background: '#0071e3', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '14px', fontWeight: 600, color: '#fff',
              }}>
                {(user.full_name || user.email)[0].toUpperCase()}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: '13px', fontWeight: 600, color: '#fff', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {user.full_name || user.email}
                </p>
                <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', margin: 0, textTransform: 'capitalize' }}>
                  {user.role}
                </p>
              </div>
              <button
                onClick={logout}
                title="Sign out"
                style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', padding: '4px' }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
                </svg>
              </button>
            </div>
          </div>
        )}
      </aside>

      {/* Main Content */}
      <main className="lg:ml-[260px] ml-0 flex-1 min-h-screen" style={{
        backgroundImage: 'url(/herobg.jpg)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundAttachment: 'fixed',
      }}>
        {/* Subtle tinted overlay — lets the cosmic image show through */}
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0, 0, 0, 0.55)',
          pointerEvents: 'none',
          zIndex: 0,
        }} />
        <div className="max-w-6xl mx-auto px-8 py-8" style={{ position: 'relative', zIndex: 1 }}>
          {/* Page Header */}
          <div className="mb-8">
            <h2 style={{ fontSize: '28px', fontWeight: 700, color: '#ffffff', letterSpacing: '-0.224px', margin: 0 }}>
              {currentPage.title}
            </h2>
            <p style={{ fontSize: '15px', color: 'rgba(255,255,255,0.6)', marginTop: '4px' }}>
              {currentPage.description}
            </p>
          </div>

          {/* Error Banner */}
          {(error || generationError) && (
            <div
              style={{
                background: '#fff',
                borderLeft: '3px solid #ff3b30',
                padding: '16px',
                borderRadius: '8px',
                boxShadow: 'rgba(0,0,0,0.04) 0px 1px 4px',
                marginBottom: '24px',
              }}
            >
              <p style={{ color: '#1d1d1f', fontSize: '14px', margin: 0 }}>
                {error || generationError}
              </p>
            </div>
          )}

          {/* Tab Content */}
          <div>
            {activeTab === 'generate' && (
              <ImageGenerator
                templates={templates}
                onGenerate={handleGenerateImages}
                isLoading={isGenerating}
                vertical={vertical}
              />
            )}

            {activeTab === 'gallery' && (
              <ImageGallery images={generatedImages} />
            )}

            {activeTab === 'script-to-audio' && (
              <ScriptToAudio />
            )}

            {activeTab === 'analytics' && (
              <Analytics data={analytics} />
            )}

            {activeTab === 'scripts' && (
              <ScriptGenerator />
            )}

            {activeTab === 'video-hook' && (
              <VideoHookAnalyzer />
            )}

            {activeTab === 'video-script' && (
              <VideoScriptAnalyzer />
            )}

            {activeTab === 'video-downloader' && (
              <VideoDownloader />
            )}

            {activeTab === 'ugc-videos' && (
              <UGCVideoStudio />
            )}

            {activeTab === 'admin' && hasPermission('admin_panel') && (
              <AdminPanel />
            )}
          </div>
        </div>
      </main>

      {/* Mobile responsive styles */}
      <style jsx global>{`
        @media (max-width: 1023px) {
          .sidebar-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.5);
            z-index: 40;
          }
        }
      `}</style>
    </div>
  );
}
