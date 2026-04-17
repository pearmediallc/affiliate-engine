'use client';

import { useState, useEffect } from 'react';
import { API_BASE_URL } from '@/lib/api';

interface GeneratedScript {
  product: string;
  vertical: string;
  target_audience: string;
  framework: string;
  angle: string;
  scripts: string;
  tips: Record<string, unknown>;
}

interface Framework {
  name: string;
  description: string;
  template: string;
}

interface Triggers {
  [key: string]: string[];
}

const ANGLE_OPTIONS = [
  { value: 'benefit', label: 'Benefit Focus' },
  { value: 'pain_point', label: 'Pain Point' },
  { value: 'social_proof', label: 'Social Proof' },
  { value: 'curiosity', label: 'Curiosity' },
  { value: 'urgency', label: 'Urgency' },
];

export default function ScriptGenerator() {
  const [product, setProduct] = useState('');
  const [vertical, setVertical] = useState('home_insurance');
  const [targetAudience, setTargetAudience] = useState('');
  const [selectedFramework, setSelectedFramework] = useState('PAS');
  const [selectedAngle, setSelectedAngle] = useState('benefit');
  const [selectedTriggers, setSelectedTriggers] = useState<string[]>([]);
  const [includeCTA, setIncludeCTA] = useState(true);
  const [desiredDuration, setDesiredDuration] = useState(30);

  const [frameworks, setFrameworks] = useState<Record<string, Framework>>({});
  const [triggers, setTriggers] = useState<Triggers>({});
  const [generatedScript, setGeneratedScript] = useState<GeneratedScript | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');

  // Load frameworks and triggers on mount
  useEffect(() => {
    const loadData = async () => {
      try {
        const [frameworksRes, triggersRes] = await Promise.all([
          fetch(`${API_BASE_URL}/scripts/frameworks`),
          fetch(`${API_BASE_URL}/scripts/triggers`),
        ]);

        const frameworksData = await frameworksRes.json();
        const triggersData = await triggersRes.json();

        setFrameworks(frameworksData.data);
        setTriggers(triggersData.data);
      } catch (err) {
        console.error('Failed to load frameworks/triggers:', err);
      }
    };

    loadData();
  }, []);

  const handleGenerateScript = async () => {
    if (!product.trim() || !targetAudience.trim()) {
      setError('Please enter product name and target audience');
      return;
    }

    try {
      setIsGenerating(true);
      setError('');

      const response = await fetch(`${API_BASE_URL}/scripts/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product,
          vertical,
          target_audience: targetAudience,
          framework: selectedFramework,
          angle: selectedAngle,
          psychological_triggers: selectedTriggers.length > 0 ? selectedTriggers : undefined,
          include_cta: includeCTA,
          desired_duration_seconds: desiredDuration,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to generate script');
      }

      const result = await response.json();
      setGeneratedScript(result.data);
    } catch (err) {
      console.error('Generation error:', err);
      setError('Failed to generate script. Please try again.');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCopyScript = () => {
    if (generatedScript?.scripts) {
      navigator.clipboard.writeText(generatedScript.scripts);
      alert('Script copied to clipboard!');
    }
  };

  const handleToggleTrigger = (trigger: string) => {
    setSelectedTriggers((prev) =>
      prev.includes(trigger)
        ? prev.filter((t) => t !== trigger)
        : [...prev, trigger]
    );
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
      {/* Form */}
      <div className="lg:col-span-1">
        <div className="card sticky top-8">
          <h2 className="text-xl font-bold mb-6">✍️ Script Generator</h2>

          <div className="space-y-4">
            {/* Product */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Product/Service
              </label>
              <input
                type="text"
                value={product}
                onChange={(e) => setProduct(e.target.value)}
                placeholder="e.g., Home Insurance Policy"
                className="input text-sm"
              />
            </div>

            {/* Target Audience */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Target Audience
              </label>
              <input
                type="text"
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
                placeholder="e.g., Homeowners over 50"
                className="input text-sm"
              />
            </div>

            {/* Framework */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Copywriting Framework
              </label>
              <select
                value={selectedFramework}
                onChange={(e) => setSelectedFramework(e.target.value)}
                className="input text-sm"
              >
                {Object.entries(frameworks).map(([key, framework]) => (
                  <option key={key} value={key}>
                    {framework.name} - {framework.description}
                  </option>
                ))}
              </select>
              {frameworks[selectedFramework] && (
                <p className="text-xs text-gray-500 mt-1">
                  {frameworks[selectedFramework].description}
                </p>
              )}
            </div>

            {/* Angle */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Psychological Angle
              </label>
              <select
                value={selectedAngle}
                onChange={(e) => setSelectedAngle(e.target.value)}
                className="input text-sm"
              >
                {ANGLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Triggers */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Psychological Triggers (Optional)
              </label>
              <div className="space-y-2 max-h-40 overflow-y-auto">
                {Object.keys(triggers).map((trigger) => (
                  <label key={trigger} className="flex items-center">
                    <input
                      type="checkbox"
                      checked={selectedTriggers.includes(trigger)}
                      onChange={() => handleToggleTrigger(trigger)}
                      className="rounded border-gray-300 text-blue-600 w-4 h-4 mr-2"
                    />
                    <span className="text-sm text-gray-700">{trigger}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Script Duration */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Script Duration
              </label>
              <select
                value={desiredDuration}
                onChange={(e) => setDesiredDuration(parseInt(e.target.value))}
                className="input text-sm"
              >
                <option value={15}>15s - Short Hook (TikTok, Reels)</option>
                <option value={30}>30s - Standard (YouTube Shorts, Facebook)</option>
                <option value={60}>60s - Extended (YouTube, Mid-roll)</option>
                <option value={90}>90s - Premium Content</option>
                <option value={120}>120s - Long-form Sales</option>
              </select>
            </div>

            {/* Include CTA */}
            <div>
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={includeCTA}
                  onChange={(e) => setIncludeCTA(e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 w-4 h-4 mr-2"
                />
                <span className="text-sm font-medium text-gray-700">
                  Include Call-to-Action
                </span>
              </label>
            </div>

            {/* Error Message */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-sm text-red-800">{error}</p>
              </div>
            )}

            {/* Generate Button */}
            <button
              onClick={handleGenerateScript}
              disabled={isGenerating || !product.trim() || !targetAudience.trim()}
              className={`w-full btn py-3 rounded-lg font-medium transition-all ${
                isGenerating || !product.trim() || !targetAudience.trim()
                  ? 'bg-gray-400 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-700 active:scale-95 text-white'
              }`}
            >
              {isGenerating ? (
                <span className="flex items-center justify-center">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></span>
                  Generating...
                </span>
              ) : (
                '✍️ Generate Script'
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Results */}
      <div className="lg:col-span-2">
        {generatedScript ? (
          <div className="card">
            <div className="flex items-start justify-between mb-6">
              <div>
                <h3 className="text-2xl font-bold text-gray-900">
                  Scripts Generated ✓
                </h3>
                <p className="text-gray-600 mt-1">
                  Using {generatedScript.framework} framework
                </p>
              </div>
              <span className="inline-block bg-green-100 text-green-800 px-3 py-1 rounded-full text-sm font-medium">
                Ready
              </span>
            </div>

            {/* Scripts Display */}
            <div className="bg-gray-50 rounded-lg p-6 mb-6">
              <p className="text-sm text-gray-600 mb-4">Generated Scripts</p>
              <div className="whitespace-pre-wrap text-sm text-gray-800 max-h-96 overflow-y-auto font-mono">
                {generatedScript.scripts}
              </div>
            </div>

            {/* Metadata */}
            <div className="grid grid-cols-2 gap-4 mb-6 py-6 border-y border-gray-200">
              <div>
                <p className="text-sm text-gray-600">Product</p>
                <p className="text-lg font-bold text-gray-900">{generatedScript.product}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Framework</p>
                <p className="text-lg font-bold text-gray-900">{generatedScript.framework}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Angle</p>
                <p className="text-lg font-bold text-gray-900">
                  {generatedScript.angle.replace('_', ' ')}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Target Audience</p>
                <p className="text-lg font-bold text-gray-900">{generatedScript.target_audience}</p>
              </div>
            </div>

            {/* Tips */}
            {generatedScript.tips && (
              <div className="mb-6">
                <h4 className="font-semibold text-gray-900 mb-3">Copywriting Tips</h4>
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
                  {generatedScript.tips.best_practices && Array.isArray(generatedScript.tips.best_practices) && (
                    <div>
                      <p className="text-sm font-semibold text-blue-900 mb-2">Best Practices:</p>
                      <ul className="text-sm text-blue-800 space-y-1">
                        {generatedScript.tips.best_practices.map((tip: string, idx: number) => (
                          <li key={idx}>• {tip}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Copy Button */}
            <button
              onClick={handleCopyScript}
              className="w-full btn btn-primary py-3 rounded-lg font-medium hover:bg-blue-700 transition"
            >
              📋 Copy Script to Clipboard
            </button>
          </div>
        ) : (
          <div className="card h-full flex items-center justify-center">
            <div className="text-center">
              <p className="text-gray-500 text-lg mb-2">✍️</p>
              <p className="text-gray-500">
                Fill in the product and audience to generate high-converting scripts
              </p>
              <p className="text-sm text-gray-400 mt-2">
                Uses proven copywriting frameworks: AIDA, PAS, StoryBrand, SLAP, BAB
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
