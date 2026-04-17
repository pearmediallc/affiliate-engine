'use client';

import { useState } from 'react';
import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

interface VideoFormat {
  format_id: string;
  ext: string;
  resolution: string;
  filesize: number | null;
}

interface VideoInfo {
  title: string;
  thumbnail: string;
  duration: number;
  formats: VideoFormat[];
}

export default function VideoDownloader() {
  const [url, setUrl] = useState('');
  const [videoInfo, setVideoInfo] = useState<VideoInfo | null>(null);
  const [selectedFormat, setSelectedFormat] = useState('');
  const [loadingInfo, setLoadingInfo] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const formatFileSize = (bytes: number | null) => {
    if (!bytes) return 'Unknown size';
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  const handleGetInfo = async () => {
    if (!url.trim()) return;
    setError('');
    setVideoInfo(null);
    setSelectedFormat('');
    setLoadingInfo(true);
    try {
      const response = await axios.post(`${API_BASE_URL}/video-download/info`, { url });
      setVideoInfo(response.data);
      if (response.data.formats?.length > 0) {
        setSelectedFormat(response.data.formats[response.data.formats.length - 1].format_id);
      }
    } catch (err: unknown) {
      const msg = axios.isAxiosError(err) ? err.response?.data?.detail || err.message : 'Failed to fetch video info';
      setError(msg);
    } finally {
      setLoadingInfo(false);
    }
  };

  const handleDownload = async () => {
    if (!url.trim()) return;
    setError('');
    setDownloading(true);
    try {
      const startRes = await axios.post(`${API_BASE_URL}/video-download/start`, {
        url,
        format_id: selectedFormat || undefined,
      });
      const { download_id, filename } = startRes.data;

      const fileRes = await axios.get(`${API_BASE_URL}/video-download/file/${download_id}`, {
        responseType: 'blob',
      });

      const blobUrl = window.URL.createObjectURL(new Blob([fileRes.data]));
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(blobUrl);
    } catch (err: unknown) {
      const msg = axios.isAxiosError(err) ? err.response?.data?.detail || err.message : 'Download failed';
      setError(msg);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="bg-white rounded-xl shadow-md p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Video Downloader</h2>
        <p className="text-gray-600 mb-6">Paste a video URL to download it to your system.</p>

        {/* URL Input */}
        <div className="flex gap-3 mb-6">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleGetInfo()}
            placeholder="https://www.youtube.com/watch?v=..."
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <button
            onClick={handleGetInfo}
            disabled={loadingInfo || !url.trim()}
            className="px-5 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {loadingInfo ? 'Loading...' : 'Get Info'}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        {/* Video Info */}
        {videoInfo && (
          <div className="border border-gray-200 rounded-lg p-4 mb-6">
            <div className="flex gap-4">
              {videoInfo.thumbnail && (
                <img
                  src={videoInfo.thumbnail}
                  alt={videoInfo.title}
                  className="w-40 h-24 object-cover rounded-lg flex-shrink-0"
                />
              )}
              <div className="min-w-0">
                <h3 className="font-medium text-gray-900 truncate">{videoInfo.title}</h3>
                {videoInfo.duration && (
                  <p className="text-sm text-gray-500 mt-1">
                    Duration: {formatDuration(videoInfo.duration)}
                  </p>
                )}
              </div>
            </div>

            {/* Format Selector */}
            {videoInfo.formats.length > 0 && (
              <div className="mt-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">Format</label>
                <select
                  value={selectedFormat}
                  onChange={(e) => setSelectedFormat(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  {videoInfo.formats.map((f) => (
                    <option key={f.format_id} value={f.format_id}>
                      {f.resolution} ({f.ext}) - {formatFileSize(f.filesize)}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Download Button */}
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="mt-4 w-full px-5 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {downloading ? 'Downloading...' : 'Download'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
