'use client';

import { useState } from 'react';
import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

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
        <h2 className="text-2xl font-bold text-gray-900">📜 Video Transcript Analyzer</h2>
        <p className="text-gray-600 mt-2">
          Upload a video or paste a link to auto-generate transcript, then analyze copywriting frameworks, psychology, and conversion mechanics
        </p>
      </div>

      {/* Input Section */}
      <div className="bg-white rounded-lg shadow p-6 space-y-4">

        <form onSubmit={handleAnalyze} className="space-y-4">

          {/* Video URL Input */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              📹 Video/Audio URL
            </label>
            <input
              type="url"
              value={videoUrl}
              onChange={(e) => setVideoUrl(e.target.value)}
              placeholder="YouTube, TikTok, Instagram, or direct video/audio link"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={!!videoFile}
            />
          </div>

          {/* OR Divider */}
          <div className="flex items-center gap-3">
            <div className="flex-1 border-t border-gray-200"></div>
            <span className="text-xs text-gray-500 font-medium">OR</span>
            <div className="flex-1 border-t border-gray-200"></div>
          </div>

          {/* File Upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              📁 Upload Video/Audio File
            </label>
            <input
              type="file"
              accept="video/*,audio/*,.mp3,.mp4,.wav,.m4a,.flac,.webm,.ogg"
              onChange={(e) => {
                const file = e.target.files?.[0] || null;
                setVideoFile(file);
                if (file) setVideoUrl('');
              }}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg text-sm file:mr-4 file:py-1 file:px-3 file:rounded-full file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            {videoFile && (
              <div className="flex items-center gap-2 mt-2">
                <span className="text-xs text-green-600">Selected: {videoFile.name} ({(videoFile.size / 1024 / 1024).toFixed(1)}MB)</span>
                <button type="button" onClick={() => setVideoFile(null)} className="text-xs text-red-500 underline">Remove</button>
              </div>
            )}
            <p className="text-xs text-gray-500 mt-1">
              Supports: MP3, MP4, WAV, M4A, FLAC, WEBM (max 25MB)
            </p>
          </div>

          {/* Transcription Provider */}
          <div className="flex items-center gap-4">
            <label className="text-sm font-medium text-gray-700">Transcription Engine:</label>
            <select
              value={transcriptionProvider}
              onChange={(e) => setTranscriptionProvider(e.target.value)}
              className="px-3 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
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
            <label className="block text-sm font-medium text-gray-700 mb-2">
              📝 Transcript {transcript ? '(edit if needed)' : '(auto-generated or paste manually)'}
            </label>
            <textarea
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder="Transcript will appear here after auto-transcription, or paste manually..."
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 h-40 resize-none font-mono text-sm"
            />
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-red-800 text-sm">{error}</p>
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
        <div className="bg-white rounded-lg shadow p-6 space-y-6">
          <div className="border-b pb-4">
            <h3 className="text-lg font-bold text-gray-900">📊 Transcript Analysis Results</h3>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-gray-600">Platform</p>
                <p className="text-sm font-semibold text-gray-900">{analysisResult.platform}</p>
              </div>
              <div>
                <p className="text-xs text-gray-600">Analysis Model</p>
                <p className="text-sm font-semibold text-gray-900">{analysisResult.analysis_model}</p>
              </div>
            </div>
          </div>

          <div>
            <h4 className="font-semibold text-gray-900 mb-3">🔍 Detailed Transcript Analysis</h4>
            <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-800 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto border border-gray-200">
              {analysisResult.detailed_analysis}
            </div>
          </div>

          {analysisResult.transcript_snippet && (
            <div className="border-t pt-4">
              <h4 className="font-semibold text-gray-900 mb-3">📋 Transcript Analyzed</h4>
              <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-800 max-h-32 overflow-y-auto border border-gray-200 font-mono">
                {analysisResult.transcript_snippet}
              </div>
            </div>
          )}

          <div className="flex gap-2 border-t pt-4">
            <button
              onClick={() => {
                navigator.clipboard.writeText(analysisResult.detailed_analysis);
                alert('Analysis copied to clipboard!');
              }}
              className="flex-1 py-2 px-4 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium text-sm transition-colors"
            >
              📋 Copy Analysis
            </button>
            <button
              onClick={() => setAnalysisResult(null)}
              className="flex-1 py-2 px-4 bg-gray-200 hover:bg-gray-300 text-gray-900 rounded-lg font-medium text-sm transition-colors"
            >
              ➕ Analyze Another
            </button>
          </div>
        </div>
      )}

      {/* Tips Section */}
      <div className="bg-purple-50 border border-purple-200 rounded-lg p-6 space-y-3">
        <h4 className="font-semibold text-purple-900">💡 Transcript Analysis Features</h4>
        <ul className="text-sm text-purple-800 space-y-2">
          <li>• <strong>Auto-Transcription</strong> - Upload video/audio or paste URL, we transcribe with Whisper/Deepgram</li>
          <li>• <strong>Framework Identification</strong> - Detect PAS, AIDA, BAB, StoryBrand, SLAP patterns</li>
          <li>• <strong>Psychology Analysis</strong> - Identify urgency, scarcity, social proof, authority triggers</li>
          <li>• <strong>Conversion Mechanics</strong> - Understand problem to desire to action flow</li>
          <li>• <strong>Replication Guide</strong> - Step-by-step breakdown to create similar hooks</li>
          <li>• <strong>Vertical Applicability</strong> - Which affiliate verticals could use this approach</li>
        </ul>
      </div>
    </div>
  );
}
