'use client';
import { useState, useEffect } from 'react';
import axios from 'axios';
import { API_BASE_URL, API_HOST } from '@/lib/api';

const JOB_TYPE_LABELS: Record<string, string> = {
  image_generation: 'Image',
  ugc_video: 'UGC Video',
  talking_head: 'Talking Head',
  veo_video: 'Video',
  script_generation: 'Script',
  ad_copy: 'Ad Copy',
  landing_page: 'Landing Page',
  lp_analysis: 'LP Analysis',
  angle_generation: 'Angles',
};

const STATUS_COLORS: Record<string, string> = {
  processing: '#ffd60a',
  completed: '#30d158',
  failed: '#ff453a',
  pending: 'rgba(255,255,255,0.4)',
};

export default function JobsPanel() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [activeCount, setActiveCount] = useState(0);

  // Poll active jobs
  useEffect(() => {
    const fetchJobs = async () => {
      try {
        const [activeRes, allRes] = await Promise.all([
          axios.get(`${API_BASE_URL}/jobs/active`).catch(() => ({ data: { data: { jobs: [] } } })),
          expanded ? axios.get(`${API_BASE_URL}/jobs/my?limit=30`).catch(() => ({ data: { data: { jobs: [] } } })) : Promise.resolve(null),
        ]);
        setActiveCount(activeRes.data?.data?.jobs?.length || 0);
        if (allRes) {
          setJobs(allRes.data?.data?.jobs || []);
        }
      } catch {}
    };
    fetchJobs();
    const interval = setInterval(fetchJobs, 10000);
    return () => clearInterval(interval);
  }, [expanded]);

  // Fetch all jobs when expanded
  useEffect(() => {
    if (expanded) {
      axios.get(`${API_BASE_URL}/jobs/my?limit=30`)
        .then(r => setJobs(r.data?.data?.jobs || []))
        .catch(() => {});
    }
  }, [expanded]);

  return (
    <>
      {/* Floating indicator */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          position: 'fixed', bottom: '24px', right: '24px', zIndex: 100,
          width: '48px', height: '48px', borderRadius: '50%',
          background: activeCount > 0 ? '#0071e3' : 'rgba(20,20,22,0.8)',
          backdropFilter: 'blur(10px)',
          border: '1px solid rgba(255,255,255,0.15)',
          color: '#fff', fontSize: '16px', fontWeight: 600,
          cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: activeCount > 0 ? '0 4px 20px rgba(0,113,227,0.4)' : '0 4px 20px rgba(0,0,0,0.3)',
          animation: activeCount > 0 ? 'pulse-glow 2s infinite' : 'none',
        }}
      >
        {activeCount > 0 ? activeCount : (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 8v4l3 3" /><circle cx="12" cy="12" r="10" /></svg>
        )}
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div style={{
          position: 'fixed', bottom: '84px', right: '24px', zIndex: 99,
          width: '380px', maxHeight: '500px', overflowY: 'auto',
          background: 'rgba(20,20,22,0.9)', backdropFilter: 'blur(20px)',
          border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px',
          boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          padding: '20px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <p style={{ fontSize: '15px', fontWeight: 600, color: '#fff', margin: 0 }}>My Jobs</p>
            <button onClick={() => setExpanded(false)} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '18px' }}>x</button>
          </div>

          {jobs.length === 0 ? (
            <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.4)', textAlign: 'center', padding: '20px 0' }}>No jobs yet</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {jobs.map(job => (
                <div key={job.id} style={{
                  padding: '12px', borderRadius: '10px',
                  background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8ed' }}>
                      {JOB_TYPE_LABELS[job.job_type] || job.job_type}
                    </span>
                    <span style={{
                      fontSize: '11px', fontWeight: 600, padding: '2px 8px', borderRadius: '4px',
                      background: `${STATUS_COLORS[job.status] || 'gray'}22`,
                      color: STATUS_COLORS[job.status] || 'gray',
                    }}>
                      {job.status}
                    </span>
                  </div>
                  <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.35)', margin: 0 }}>
                    {new Date(job.created_at).toLocaleString()}
                    {job.vertical ? ` \u00b7 ${job.vertical}` : ''}
                    {job.cost_usd ? ` \u00b7 $${job.cost_usd}` : ''}
                  </p>
                  {job.status === 'completed' && job.result_url && (
                    <a href={job.result_url.startsWith('/') ? `${API_HOST}${job.result_url}` : job.result_url}
                      target="_blank" rel="noopener"
                      style={{ fontSize: '12px', color: '#2997ff', display: 'block', marginTop: '6px' }}>
                      View Result
                    </a>
                  )}
                  {job.status === 'failed' && job.error_message && (
                    <p style={{ fontSize: '11px', color: '#ff6b6b', marginTop: '4px' }}>{job.error_message}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <style jsx global>{`
        @keyframes pulse-glow {
          0%, 100% { box-shadow: 0 4px 20px rgba(0,113,227,0.4); }
          50% { box-shadow: 0 4px 30px rgba(0,113,227,0.7); }
        }
      `}</style>
    </>
  );
}
