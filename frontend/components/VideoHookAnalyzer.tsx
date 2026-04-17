'use client';

import { useState } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '@/lib/api';

export default function VideoHookAnalyzer() {
  const [videoUrl, setVideoUrl] = useState('');
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [hookDuration, setHookDuration] = useState(5);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<any>(null);
  const [error, setError] = useState('');

  const handleAnalyzeHook = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!videoUrl.trim() && !videoFile) {
      setError('Please enter a video URL or upload a video file');
      return;
    }

    setIsAnalyzing(true);
    setError('');
    setAnalysisResult(null);

    try {
      let response;

      if (videoFile) {
        // Upload file for analysis
        const formData = new FormData();
        formData.append('file', videoFile);
        formData.append('hook_duration_seconds', hookDuration.toString());
        response = await axios.post(
          `${API_BASE_URL}/video-analysis/analyze-hook-upload`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } }
        );
      } else {
        response = await axios.post(`${API_BASE_URL}/video-analysis/analyze-hook`, {
          video_url: videoUrl,
          hook_duration_seconds: hookDuration,
        });
      }

      if (response.data.success) {
        setAnalysisResult(response.data.data);
      } else {
        setError('Analysis failed. Please try again.');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to analyze video hook');
      console.error('Error:', err);
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900">🎬 Video Hook Analyzer</h2>
        <p className="text-gray-600 mt-2">
          Analyze any viral video's hook using Gemma AI to understand what makes it convert
        </p>
      </div>

      {/* Input Section */}
      <div className="bg-white rounded-lg shadow p-6 space-y-4">
        <form onSubmit={handleAnalyzeHook} className="space-y-4">

          {/* Video URL Input */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              📹 Video URL
            </label>
            <input
              type="url"
              value={videoUrl}
              onChange={(e) => { setVideoUrl(e.target.value); if (e.target.value) setVideoFile(null); }}
              placeholder="Enter YouTube, TikTok, Instagram, or direct video link"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={!!videoFile}
            />
            <p className="text-xs text-gray-500 mt-1">
              Supports: YouTube, TikTok, Instagram, and direct video links
            </p>
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
              📁 Upload Video File
            </label>
            <input
              type="file"
              accept="video/*,.mp4,.mov,.avi,.webm"
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
          </div>

          {/* Hook Duration */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              ⏱️ Hook Duration to Analyze
            </label>
            <div className="flex items-center gap-4">
              <input
                type="range"
                min="3"
                max="15"
                value={hookDuration}
                onChange={(e) => setHookDuration(parseInt(e.target.value))}
                className="flex-1 h-2 bg-gray-200 rounded-lg cursor-pointer"
              />
              <span className="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm font-bold min-w-20 text-center">
                {hookDuration}s
              </span>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Typical effective hooks are 5-10 seconds
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-red-800 text-sm">{error}</p>
            </div>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isAnalyzing || (!videoUrl.trim() && !videoFile)}
            className={`w-full py-3 px-4 rounded-lg font-medium text-white transition-all ${
              isAnalyzing || (!videoUrl.trim() && !videoFile)
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
              '🔍 Analyze Hook'
            )}
          </button>
        </form>
      </div>

      {/* Analysis Results */}
      {analysisResult && (
        <div className="bg-white rounded-lg shadow p-6 space-y-6">
          <div className="border-b pb-4">
            <h3 className="text-lg font-bold text-gray-900">📊 Analysis Results</h3>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-gray-600">Platform</p>
                <p className="text-sm font-semibold text-gray-900">{analysisResult.platform}</p>
              </div>
              <div>
                <p className="text-xs text-gray-600">Video ID</p>
                <p className="text-sm font-semibold text-gray-900">{analysisResult.video_id}</p>
              </div>
              <div>
                <p className="text-xs text-gray-600">Hook Duration Analyzed</p>
                <p className="text-sm font-semibold text-gray-900">{analysisResult.hook_duration_seconds} seconds</p>
              </div>
              <div>
                <p className="text-xs text-gray-600">Analysis Model</p>
                <p className="text-sm font-semibold text-gray-900">{analysisResult.analysis_model}</p>
              </div>
            </div>
          </div>

          <div>
            <h4 className="font-semibold text-gray-900 mb-3">🔍 Hook Analysis</h4>
            <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-800 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">
              {analysisResult.hook_analysis || analysisResult.detailed_analysis}
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => {
                const text = analysisResult.hook_analysis || analysisResult.detailed_analysis;
                navigator.clipboard.writeText(text);
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
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 space-y-3">
        <h4 className="font-semibold text-blue-900">💡 Visual Hook Analysis</h4>
        <ul className="text-sm text-blue-800 space-y-2">
          <li>• <strong>Paste any video URL</strong> or upload a video file directly</li>
          <li>• <strong>Adjust hook duration</strong> to analyze the most critical part (usually 5-10 seconds)</li>
          <li>• <strong>Get visual analysis</strong> - attention grabbers, composition, movement, text overlays</li>
          <li>• <strong>Identify psychology</strong> - emotional triggers and conversion elements</li>
          <li>• <strong>Replicate success</strong> - apply winning visual patterns to your affiliate ads</li>
          <li>• <strong>For transcript analysis</strong> - use the "📜 Video Transcript Analyzer" tab</li>
        </ul>
      </div>
    </div>
  );
}
