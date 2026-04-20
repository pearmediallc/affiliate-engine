'use client';

import { useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '@/lib/api';

export default function VideoScriptAnalyzer() {
  const [videoUrl, setVideoUrl] = useState('');
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState('');
  const [hookDuration] = useState(5); // kept for API compat but not shown in UI
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [transcriptionProvider, setTranscriptionProvider] = useState('openai');

  const handleTranscribe = async () => {
    setError('');
    setIsTranscribing(true);

    try {
      let result;

      if (videoFile) {
        // Upload file for transcription
        const formData = new FormData();
        formData.append('file', videoFile);
        formData.append('provider', transcriptionProvider);

        const response = await axios.post(
          `${API_BASE_URL}/transcription/transcribe-file`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } }
        );
        result = response.data;
      } else if (videoUrl.trim()) {
        // Transcribe from URL
        const response = await axios.post(
          `${API_BASE_URL}/transcription/transcribe-url`,
          {
            audio_url: videoUrl,
            provider: transcriptionProvider,
          }
        );
        result = response.data;
      } else {
        setError('Please provide a video URL or upload a video/audio file');
        setIsTranscribing(false);
        return;
      }

      if (result.success && result.data?.transcription) {
        setTranscript(result.data.transcription);
      } else {
        setError('Transcription returned empty result');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Transcription failed. You can also paste the transcript manually below.');
      console.error('Transcription error:', err);
    } finally {
      setIsTranscribing(false);
    }
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!transcript.trim()) {
      setError('Please generate or paste a transcript first');
      return;
    }

    setIsAnalyzing(true);
    setError('');
    setAnalysisResult(null);

    try {
      const response = await axios.post(
        `${API_BASE_URL}/video-analysis/analyze-with-transcript`,
        {
          video_url: videoUrl || 'uploaded-file',
          transcript_text: transcript,
          hook_duration_seconds: hookDuration,
        }
      );

      if (response.data.success) {
        setAnalysisResult(response.data.data);
      } else {
        setError('Analysis failed. Please try again.');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to analyze transcript');
      console.error('Error:', err);
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 style={{ fontSize: '24px', fontWeight: 700, color: '#e8e8ed' }}>Video Transcript Analyzer</h2>
        <p style={{ color: 'rgba(255,255,255,0.6)', marginTop: '8px', fontSize: '14px' }}>
          Upload a video or paste a link to auto-generate transcript, then analyze copywriting frameworks, psychology, and conversion mechanics
        </p>
      </div>

      {/* Input Section */}
      <div className="card" style={{ padding: '24px' }}>

        <form onSubmit={handleAnalyze} className="space-y-4">

          {/* Video URL Input */}
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
              Video/Audio URL
            </label>
            <input
              type="url"
              value={videoUrl}
              onChange={(e) => setVideoUrl(e.target.value)}
              placeholder="YouTube, TikTok, Instagram, or direct video/audio link"
              style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', outline: 'none' }}
              disabled={!!videoFile}
            />
          </div>

          {/* OR Divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ flex: 1, borderTop: '1px solid rgba(255,255,255,0.1)' }}></div>
            <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', fontWeight: 500 }}>OR</span>
            <div style={{ flex: 1, borderTop: '1px solid rgba(255,255,255,0.1)' }}></div>
          </div>

          {/* File Upload */}
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
              Upload Video/Audio File
            </label>
            <input
              type="file"
              accept="video/*,audio/*,.mp3,.mp4,.wav,.m4a,.flac,.webm,.ogg"
              onChange={(e) => {
                const file = e.target.files?.[0] || null;
                setVideoFile(file);
                if (file) setVideoUrl('');
              }}
              style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px' }}
            />
            {videoFile && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                <span style={{ fontSize: '12px', color: '#30d158' }}>Selected: {videoFile.name} ({(videoFile.size / 1024 / 1024).toFixed(1)}MB)</span>
                <button type="button" onClick={() => setVideoFile(null)} style={{ fontSize: '12px', color: '#ff6b6b', background: 'none', border: 'none', textDecoration: 'underline', cursor: 'pointer' }}>Remove</button>
              </div>
            )}
            <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', marginTop: '6px' }}>
              Supports: MP3, MP4, WAV, M4A, FLAC, WEBM (max 100MB)
            </p>
          </div>

          {/* Transcription Provider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)' }}>Transcription Engine:</label>
            <select
              value={transcriptionProvider}
              onChange={(e) => setTranscriptionProvider(e.target.value)}
              style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '13px', outline: 'none' }}
            >
              <option value="openai">OpenAI Whisper</option>
              <option value="deepgram">Deepgram</option>
            </select>
          </div>

          {/* Auto-Transcribe Button */}
          <button
            type="button"
            onClick={handleTranscribe}
            disabled={isTranscribing || (!videoUrl.trim() && !videoFile)}
            className={`w-full py-2 px-4 rounded-lg font-medium text-white transition-all ${
              isTranscribing || (!videoUrl.trim() && !videoFile)
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-green-600 hover:bg-green-700 active:scale-95'
            }`}
          >
            {isTranscribing ? (
              <span className="flex items-center justify-center">
                <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></span>
                Transcribing with {transcriptionProvider === 'openai' ? 'Whisper' : 'Deepgram'}...
              </span>
            ) : (
              '🎤 Auto-Transcribe'
            )}
          </button>

          {/* Transcript Display/Edit */}
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
              Transcript {transcript ? '(edit if needed)' : '(auto-generated or paste manually)'}
            </label>
            <textarea
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder="Transcript will appear here after auto-transcription, or paste manually..."
              style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', color: '#e8e8ed', fontSize: '14px', outline: 'none', resize: 'none', height: '160px', fontFamily: 'monospace' }}
            />
          </div>

          {/* Error Message */}
          {error && (
            <div style={{ background: 'rgba(255,59,48,0.1)', border: '1px solid rgba(255,59,48,0.3)', borderRadius: '10px', padding: '16px' }}>
              <p style={{ color: '#ff6b6b', fontSize: '13px', margin: 0 }}>{error}</p>
            </div>
          )}

          {/* Analyze Button */}
          <button
            type="submit"
            disabled={isAnalyzing || !transcript.trim()}
            className={`w-full py-3 px-4 rounded-lg font-medium text-white transition-all ${
              isAnalyzing || !transcript.trim()
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700 active:scale-95'
            }`}
          >
            {isAnalyzing ? (
              <span className="flex items-center justify-center">
                <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></span>
                Analyzing with Gemma...
              </span>
            ) : (
              '🔍 Analyze Transcript'
            )}
          </button>
        </form>
      </div>

      {/* Analysis Results */}
      {analysisResult && (
        <div className="card" style={{ padding: '24px' }}>
          <div style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '16px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: 700, color: '#e8e8ed' }}>Transcript Analysis Results</h3>
            <div style={{ marginTop: '12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div>
                <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>Platform</p>
                <p style={{ fontSize: '14px', fontWeight: 600, color: '#e8e8ed' }}>{analysisResult.platform}</p>
              </div>
              <div>
                <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>Analysis Model</p>
                <p style={{ fontSize: '14px', fontWeight: 600, color: '#e8e8ed' }}>{analysisResult.analysis_model}</p>
              </div>
            </div>
          </div>

          <div style={{ marginTop: '24px' }}>
            <h4 style={{ fontWeight: 600, color: '#e8e8ed', marginBottom: '12px' }}>Detailed Transcript Analysis</h4>
            <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '16px', fontSize: '14px', color: 'rgba(255,255,255,0.8)', whiteSpace: 'pre-wrap', lineHeight: 1.6, maxHeight: '384px', overflowY: 'auto', border: '1px solid rgba(255,255,255,0.08)' }}>
              {analysisResult.detailed_analysis}
            </div>
          </div>

          {analysisResult.transcript_snippet && (
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '16px', marginTop: '24px' }}>
              <h4 style={{ fontWeight: 600, color: '#e8e8ed', marginBottom: '12px' }}>Transcript Analyzed</h4>
              <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '10px', padding: '16px', fontSize: '14px', color: 'rgba(255,255,255,0.8)', maxHeight: '128px', overflowY: 'auto', border: '1px solid rgba(255,255,255,0.08)', fontFamily: 'monospace' }}>
                {analysisResult.transcript_snippet}
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '16px', marginTop: '24px' }}>
            <button
              onClick={() => {
                navigator.clipboard.writeText(analysisResult.detailed_analysis);
                alert('Analysis copied to clipboard!');
              }}
              style={{ flex: 1, padding: '10px 16px', background: '#0071e3', color: '#fff', borderRadius: '10px', border: 'none', fontWeight: 500, fontSize: '14px', cursor: 'pointer' }}
            >
              Copy Analysis
            </button>
            <button
              onClick={() => setAnalysisResult(null)}
              style={{ flex: 1, padding: '10px 16px', background: 'rgba(255,255,255,0.08)', color: '#e8e8ed', borderRadius: '10px', border: 'none', fontWeight: 500, fontSize: '14px', cursor: 'pointer' }}
            >
              Analyze Another
            </button>
          </div>
        </div>
      )}

      {/* Tips Section */}
      <div className="card" style={{ padding: '24px', border: '1px solid rgba(175,130,255,0.2)' }}>
        <h4 style={{ fontWeight: 600, color: '#bf9aff', marginBottom: '12px' }}>Transcript Analysis Features</h4>
        <ul style={{ fontSize: '14px', color: 'rgba(255,255,255,0.7)', listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <li>&#8226; <strong>Auto-Transcription</strong> - Upload video/audio or paste URL, we transcribe with Whisper/Deepgram</li>
          <li>&#8226; <strong>Framework Identification</strong> - Detect PAS, AIDA, BAB, StoryBrand, SLAP patterns</li>
          <li>&#8226; <strong>Psychology Analysis</strong> - Identify urgency, scarcity, social proof, authority triggers</li>
          <li>&#8226; <strong>Conversion Mechanics</strong> - Understand problem to desire to action flow</li>
          <li>&#8226; <strong>Replication Guide</strong> - Step-by-step breakdown to create similar hooks</li>
          <li>&#8226; <strong>Vertical Applicability</strong> - Which affiliate verticals could use this approach</li>
        </ul>
      </div>
    </div>
  );
}
