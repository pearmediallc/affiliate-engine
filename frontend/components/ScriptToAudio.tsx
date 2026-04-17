'use client';

import { useState, useEffect } from 'react';
import { generateSpeech, getSpeechVoices } from '@/lib/api';

export default function ScriptToAudio() {
  const [script, setScript] = useState('');
  const [voice, setVoice] = useState('Kore');
  const [style, setStyle] = useState('professional');
  const [language, setLanguage] = useState('en');
  const [isGenerating, setIsGenerating] = useState(false);
  const [audioData, setAudioData] = useState<string | null>(null);
  const [voices, setVoices] = useState<Record<string, string>>({});
  const [error, setError] = useState('');

  // Load available voices on mount
  useEffect(() => {
    const loadVoices = async () => {
      try {
        const result = await getSpeechVoices();
        setVoices(result.voices || {});
      } catch (err) {
        console.error('Failed to load voices:', err);
      }
    };
    loadVoices();
  }, []);

  const handleGenerateAudio = async () => {
    if (!script.trim()) {
      setError('Please enter a script');
      return;
    }

    try {
      setIsGenerating(true);
      setError('');

      const result = await generateSpeech({
        text: script,
        voice,
        style: style || undefined,
        language,
        output_format: 'mp3',
      });

      if (result.success && result.data.audio_base64) {
        setAudioData(result.data.audio_base64);
      } else {
        setError('Failed to generate audio');
      }
    } catch (err) {
      console.error('Audio generation error:', err);
      setError(`Failed to generate audio: ${err}`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownload = () => {
    if (!audioData) return;

    try {
      const binaryString = atob(audioData);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      const blob = new Blob([bytes], { type: 'audio/wav' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `affiliate-script-${voice}-${Date.now()}.wav`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download failed:', err);
      setError('Failed to download audio');
    }
  };

  const styleOptions = [
    'professional',
    'excited',
    'calm',
    'confident',
    'whispers',
    'energetic',
    'soothing',
    'engaging',
  ];

  const languageOptions = [
    { code: 'en', name: 'English' },
    { code: 'es', name: 'Spanish' },
    { code: 'fr', name: 'French' },
    { code: 'de', name: 'German' },
    { code: 'it', name: 'Italian' },
    { code: 'pt', name: 'Portuguese' },
    { code: 'ja', name: 'Japanese' },
    { code: 'zh', name: 'Chinese' },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
      {/* Form */}
      <div className="lg:col-span-1">
        <div className="card sticky top-8">
          <h2 className="text-xl font-bold mb-6">🎙️ Script to Audio</h2>

          <div className="space-y-4">
            {/* Script Input */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Affiliate Script
              </label>
              <textarea
                value={script}
                onChange={(e) => setScript(e.target.value)}
                placeholder="Enter your affiliate script here... Include conversion angles, CTAs, and emotional hooks..."
                className="input h-32 resize-none text-sm"
                maxLength={5000}
              />
              <p className="text-xs text-gray-500 mt-1">
                {script.length}/5000 characters
              </p>
            </div>

            {/* Voice Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Voice
              </label>
              <select
                value={voice}
                onChange={(e) => setVoice(e.target.value)}
                className="input text-sm"
              >
                {Object.entries(voices).map(([name, description]) => (
                  <option key={name} value={name}>
                    {name} - {description}
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                {voices[voice] || 'Select a voice'}
              </p>
            </div>

            {/* Style */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Tone/Style
              </label>
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="input text-sm"
              >
                {styleOptions.map((s) => (
                  <option key={s} value={s}>
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                Controls emotion and delivery style
              </p>
            </div>

            {/* Language */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Language
              </label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="input text-sm"
              >
                {languageOptions.map(({ code, name }) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </div>

            {/* Error Message */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-sm text-red-800">{error}</p>
              </div>
            )}

            {/* Generate Button */}
            <button
              onClick={handleGenerateAudio}
              disabled={isGenerating || !script.trim()}
              className={`w-full btn py-3 rounded-lg font-medium transition-all ${
                isGenerating || !script.trim()
                  ? 'bg-gray-400 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-700 active:scale-95 text-white'
              }`}
            >
              {isGenerating ? (
                <span className="flex items-center justify-center">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></span>
                  Generating Audio...
                </span>
              ) : (
                '🎧 Generate Audio'
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Preview/Playback */}
      <div className="lg:col-span-2">
        {audioData ? (
          <div className="card">
            <div className="flex items-start justify-between mb-6">
              <div>
                <h3 className="text-2xl font-bold text-gray-900">
                  Audio Generated ✓
                </h3>
                <p className="text-gray-600 mt-1">
                  Your affiliate script is ready to use
                </p>
              </div>
              <span className="inline-block bg-green-100 text-green-800 px-3 py-1 rounded-full text-sm font-medium">
                Ready
              </span>
            </div>

            {/* Audio Player */}
            <div className="bg-gray-50 rounded-lg p-6 mb-6">
              <p className="text-sm text-gray-600 mb-4">Audio Playback</p>
              <audio
                controls
                className="w-full"
                src={`data:audio/wav;base64,${audioData}`}
              >
                Your browser does not support the audio element.
              </audio>
            </div>

            {/* Metadata */}
            <div className="grid grid-cols-2 gap-4 mb-6 py-6 border-y border-gray-200">
              <div>
                <p className="text-sm text-gray-600">Voice</p>
                <p className="text-lg font-bold text-gray-900">{voice}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Style</p>
                <p className="text-lg font-bold text-gray-900">
                  {style.charAt(0).toUpperCase() + style.slice(1)}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Language</p>
                <p className="text-lg font-bold text-gray-900">
                  {languageOptions.find((l) => l.code === language)?.name}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Format</p>
                <p className="text-lg font-bold text-gray-900">WAV Audio</p>
              </div>
            </div>

            {/* Script Preview */}
            <div className="mb-6">
              <h4 className="font-semibold text-gray-900 mb-2">Script Used</h4>
              <p className="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap bg-gray-50 p-4 rounded-lg max-h-40 overflow-y-auto">
                {script}
              </p>
            </div>

            {/* Download Button */}
            <button
              onClick={handleDownload}
              className="w-full btn btn-primary py-3 rounded-lg font-medium hover:bg-blue-700 transition"
            >
              ⬇️ Download Audio (WAV)
            </button>
          </div>
        ) : (
          <div className="card h-full flex items-center justify-center">
            <div className="text-center">
              <p className="text-gray-500 text-lg mb-2">🎙️</p>
              <p className="text-gray-500">
                Enter your affiliate script and generate audio to preview and download
              </p>
              <p className="text-sm text-gray-400 mt-2">
                Supports 90+ languages and 30+ voices
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
