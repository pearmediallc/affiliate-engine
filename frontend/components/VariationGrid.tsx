'use client';

import { useState } from 'react';
import { reviewVariation, editVariation, API_HOST } from '../lib/api';

interface Shot {
  id: string;
  sequence_num: number;
  shot_type: string;
  status: string;
  video_url: string | null;
  duration: number;
  cost_usd: number;
}

interface Variation {
  id: string;
  campaign_id: string;
  variation_type: string;
  label: string;
  status: string;
  review_status: string;
  final_video_url: string | null;
  final_video_9_16: string | null;
  final_video_1_1: string | null;
  total_cost_usd: number;
  shots?: Shot[];
}

interface Props {
  campaignId: string;
  variations: Variation[];
  onReload: () => void;
}

const REVIEW_COLORS: Record<string, string> = {
  pending: 'border-gray-700',
  approved: 'border-green-600',
  rejected: 'border-red-700',
  regenerate_requested: 'border-yellow-600',
};

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  pending: { label: 'Pending', color: 'text-gray-400' },
  generating: { label: 'Generating…', color: 'text-yellow-400' },
  editing: { label: 'Editing…', color: 'text-orange-400' },
  completed: { label: 'Ready', color: 'text-green-400' },
  failed: { label: 'Failed', color: 'text-red-400' },
};

export default function VariationGrid({ campaignId, variations, onReload }: Props) {
  const [activePreview, setActivePreview] = useState<{ url: string; label: string } | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [aspectView, setAspectView] = useState<Record<string, '16:9' | '9:16' | '1:1'>>({});

  function getVideoUrl(v: Variation, aspect: '16:9' | '9:16' | '1:1'): string | null {
    if (aspect === '9:16') return v.final_video_9_16 ? `${API_HOST}${v.final_video_9_16}` : null;
    if (aspect === '1:1') return v.final_video_1_1 ? `${API_HOST}${v.final_video_1_1}` : null;
    return v.final_video_url ? `${API_HOST}${v.final_video_url}` : null;
  }

  async function handleReview(v: Variation, action: 'approve' | 'reject') {
    setLoadingId(v.id);
    try {
      await reviewVariation(campaignId, v.id, action);
      onReload();
    } catch {}
    setLoadingId(null);
  }

  async function handleEdit(v: Variation) {
    setLoadingId(v.id);
    try {
      await editVariation(campaignId, v.id);
      onReload();
    } catch {}
    setLoadingId(null);
  }

  if (variations.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <div className="text-4xl mb-3">🎬</div>
        <p>No variations yet. Run the edit step or create variants.</p>
      </div>
    );
  }

  return (
    <>
      {/* Preview modal */}
      {activePreview && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50" onClick={() => setActivePreview(null)}>
          <div className="relative max-w-2xl w-full mx-4" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setActivePreview(null)}
              className="absolute -top-8 right-0 text-gray-400 hover:text-white text-sm"
            >
              ✕ Close
            </button>
            <div className="bg-gray-900 rounded-xl overflow-hidden border border-gray-700">
              <div className="p-3 border-b border-gray-700 text-sm font-medium">{activePreview.label}</div>
              <video
                src={activePreview.url}
                controls
                autoPlay
                className="w-full max-h-[70vh] object-contain bg-black"
              />
            </div>
          </div>
        </div>
      )}

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {variations.map(v => {
          const aspect = aspectView[v.id] || '9:16';
          const videoUrl = getVideoUrl(v, aspect);
          const st = STATUS_LABEL[v.status] || { label: v.status, color: 'text-gray-400' };
          const borderClass = REVIEW_COLORS[v.review_status] || 'border-gray-700';

          return (
            <div key={v.id} className={`bg-gray-900 rounded-xl border-2 ${borderClass} overflow-hidden`}>

              {/* Video preview */}
              <div className="relative bg-black aspect-video flex items-center justify-center">
                {videoUrl ? (
                  <>
                    <video
                      src={videoUrl}
                      className="w-full h-full object-contain cursor-pointer"
                      muted
                      loop
                      onMouseEnter={e => (e.target as HTMLVideoElement).play()}
                      onMouseLeave={e => { (e.target as HTMLVideoElement).pause(); (e.target as HTMLVideoElement).currentTime = 0; }}
                    />
                    <button
                      onClick={() => setActivePreview({ url: videoUrl, label: v.label })}
                      className="absolute bottom-2 right-2 px-2 py-1 bg-black/60 hover:bg-black/80 rounded text-xs text-white"
                    >
                      ⛶ Expand
                    </button>
                  </>
                ) : (
                  <div className="text-gray-600 text-center p-4">
                    <div className="text-3xl mb-1">{v.status === 'generating' ? '⚙️' : '🎞️'}</div>
                    <p className={`text-xs ${st.color}`}>{st.label}</p>
                  </div>
                )}
              </div>

              {/* Info row */}
              <div className="p-3">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="text-sm font-medium">{v.label}</p>
                    <p className="text-xs text-gray-500">{v.variation_type}</p>
                  </div>
                  <div className="text-right">
                    <p className={`text-xs ${st.color}`}>{st.label}</p>
                    {v.total_cost_usd > 0 && <p className="text-xs text-gray-600">${v.total_cost_usd.toFixed(3)}</p>}
                  </div>
                </div>

                {/* Aspect toggle */}
                {v.status === 'completed' && (
                  <div className="flex gap-1 mb-3">
                    {(['9:16', '1:1', '16:9'] as const).map(a => (
                      <button
                        key={a}
                        onClick={() => setAspectView(prev => ({ ...prev, [v.id]: a }))}
                        className={`px-2 py-0.5 rounded text-xs ${aspect === a ? 'bg-violet-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
                      >
                        {a}
                      </button>
                    ))}
                  </div>
                )}

                {/* Actions */}
                <div className="flex gap-2">
                  {v.status === 'completed' && v.review_status === 'pending' && (
                    <>
                      <button
                        onClick={() => handleReview(v, 'approve')}
                        disabled={loadingId === v.id}
                        className="flex-1 py-1.5 bg-green-800 hover:bg-green-700 disabled:opacity-50 rounded-lg text-xs font-medium"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleReview(v, 'reject')}
                        disabled={loadingId === v.id}
                        className="flex-1 py-1.5 bg-red-900 hover:bg-red-800 disabled:opacity-50 rounded-lg text-xs font-medium"
                      >
                        Reject
                      </button>
                    </>
                  )}
                  {v.review_status === 'approved' && (
                    <div className="flex-1 py-1.5 bg-green-900/40 border border-green-700 rounded-lg text-xs text-center text-green-400">
                      ✓ Approved
                    </div>
                  )}
                  {v.review_status === 'rejected' && (
                    <div className="flex-1 py-1.5 bg-red-900/30 border border-red-800 rounded-lg text-xs text-center text-red-400">
                      ✕ Rejected
                    </div>
                  )}
                  {v.status === 'generating' && (
                    <div className="flex-1 py-1.5 bg-gray-800 rounded-lg text-xs text-center text-yellow-400 animate-pulse">
                      Generating…
                    </div>
                  )}
                  {v.status === 'editing' && (
                    <button
                      onClick={() => handleEdit(v)}
                      disabled={loadingId === v.id}
                      className="flex-1 py-1.5 bg-orange-900 hover:bg-orange-800 disabled:opacity-50 rounded-lg text-xs"
                    >
                      Run Edit
                    </button>
                  )}
                  {v.status === 'failed' && (
                    <button
                      onClick={onReload}
                      className="flex-1 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-red-400"
                    >
                      Retry
                    </button>
                  )}

                  {/* Download */}
                  {videoUrl && (
                    <a
                      href={videoUrl}
                      download
                      className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-xs text-gray-300"
                      title="Download"
                    >
                      ↓
                    </a>
                  )}
                </div>

                {/* Shot summary if editing/generating */}
                {v.shots && v.shots.length > 0 && v.status !== 'completed' && (
                  <div className="mt-2 flex gap-1 flex-wrap">
                    {v.shots.map(s => (
                      <div
                        key={s.id}
                        title={`Shot ${s.sequence_num}: ${s.status}`}
                        className={`w-4 h-4 rounded-sm ${
                          s.status === 'completed' ? 'bg-green-600' :
                          s.status === 'generating' ? 'bg-yellow-600 animate-pulse' :
                          s.status === 'failed' ? 'bg-red-700' : 'bg-gray-700'
                        }`}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
