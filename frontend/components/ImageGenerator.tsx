'use client';

import { useState, useEffect } from 'react';
import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

const VERTICAL_CONTEXTS = {
  home_insurance: "Family safety, property protection, financial security for homeowners",
  concealed_carry: "Legal gun ownership, responsible self-defense, permit acquisition",
  health_insurance: "Medical coverage, preventive care, family health protection",
  life_insurance: "Family financial security, income replacement, legacy planning",
  auto_insurance: "Vehicle protection, safe driving, affordable coverage",
  medicare: "Comprehensive Medicare supplement coverage, AEP enrollment, gap protection for seniors 65+",
  nutra: "Weight loss transformation, rapid results (30-60 days), metabolism boost, body confidence",
  ed: "Erectile dysfunction support, relationship confidence, natural performance enhancement, clinical results",
  bizop: "Work-from-home freedom, passive income, location independence, entrepreneurship, $5K-$10K monthly potential",
  home_improvement: "Kitchen/bathroom transformation, contractor reliability, home value increase, professional renovation quality",
  refinance: "Monthly payment reduction, rate lock optimization, debt consolidation, mortgage savings, cash-out options",
  wifi: "Whole-home WiFi coverage, seamless connectivity, multi-device support, WiFi 7 technology, speed performance",
  cbd: "Natural wellness relief, stress management, sleep improvement, lab-tested purity, hemp-derived benefits",
  blood_sugar: "Blood sugar management, stable energy, pre-diabetes prevention, glucose control, clinical formula"
};

export default function ImageGenerator({ templates, onGenerate, isLoading, vertical = "home_insurance" }) {
  const [selectedTemplate, setSelectedTemplate] = useState(templates[0]?.id || '');
  const [context, setContext] = useState(VERTICAL_CONTEXTS[vertical] || '');
  const [verticalContext, setVerticalContext] = useState(VERTICAL_CONTEXTS[vertical] || '');
  const [useCustomPrompt, setUseCustomPrompt] = useState(false);
  const [customPrompt, setCustomPrompt] = useState('');
  const [numVariations, setNumVariations] = useState(5);
  const [useGemmaVariations, setUseGemmaVariations] = useState(false);
  const [referenceInput, setReferenceInput] = useState('');
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [useAffiliateAngles, setUseAffiliateAngles] = useState(true);
  const [selectedAngle, setSelectedAngle] = useState('benefit');
  const [selectedStyle, setSelectedStyle] = useState('professional_photography');

  // Prompt Assistant state
  const [assistantDescription, setAssistantDescription] = useState('');
  const [assistantPrompt, setAssistantPrompt] = useState('');
  const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);
  const [promptError, setPromptError] = useState('');

  const handleGeneratePrompt = async () => {
    if (!assistantDescription.trim()) return;
    setIsGeneratingPrompt(true);
    setPromptError('');
    try {
      const res = await axios.post(`${API_BASE_URL}/images/generate-prompt`, {
        description: assistantDescription,
        vertical,
        style: selectedStyle,
      });
      if (res.data.success) {
        setAssistantPrompt(res.data.data.prompt);
      } else {
        setPromptError(res.data.message || 'Failed to generate prompt');
      }
    } catch (err: any) {
      setPromptError(err.response?.data?.detail || err.message || 'Failed to generate prompt');
    } finally {
      setIsGeneratingPrompt(false);
    }
  };

  const handleUsePrompt = () => {
    setCustomPrompt(assistantPrompt);
    setUseCustomPrompt(true);
    setUseGemmaVariations(false);
    setAssistantPrompt('');
    setAssistantDescription('');
  };

  // Update context when vertical changes
  useEffect(() => {
    const newContext = VERTICAL_CONTEXTS[vertical] || '';
    setVerticalContext(newContext);
    setContext(newContext);
  }, [vertical]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (useGemmaVariations) {
      if (!referenceInput && !referenceFile) {
        alert('Please provide a reference (text or image) for Gemini Vision variations');
        return;
      }
    } else if (useCustomPrompt) {
      if (!customPrompt) {
        alert('Please enter a custom prompt');
        return;
      }
    } else {
      if (!selectedTemplate) {
        alert('Please select a template');
        return;
      }
    }

    // If using Gemma variations with an image, convert to base64
    let imageBase64: string | null = null;
    if (useGemmaVariations && referenceFile) {
      try {
        const base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => {
            const result = reader.result as string;
            // Extract base64 part after comma
            const base64String = result.split(',')[1] || result;
            resolve(base64String);
          };
          reader.onerror = () => reject(reader.error);
          reader.readAsDataURL(referenceFile);
        });
        imageBase64 = base64;
      } catch (err) {
        console.error('Error converting image to base64:', err);
        alert('Failed to process image file');
        return;
      }
    }

    // Prepare data
    const data = {
      templateId: selectedTemplate,
      context: context,
      customPrompt: customPrompt,
      numVariations: numVariations,
      useGemmaVariations: useGemmaVariations,
      referenceInput: referenceInput,
      referenceImageBase64: imageBase64,
    };

    // Call with all params including image data
    onGenerate(
      selectedTemplate,
      useGemmaVariations ? referenceInput : (useCustomPrompt ? customPrompt : verticalContext),
      numVariations,
      useAffiliateAngles,
      selectedAngle,
      useGemmaVariations,
      imageBase64,
      referenceInput,
      undefined, // vertical will come from Dashboard
      selectedStyle
    );
  };

  const template = templates.find((t) => t.id === selectedTemplate);

  const [showAdvanced, setShowAdvanced] = useState(false);

  // Determine current mode
  const mode = useGemmaVariations ? 'gemma' : useCustomPrompt ? 'custom' : 'template';

  return (
    <div className="max-w-2xl mx-auto">
      <form onSubmit={handleSubmit} className="space-y-5">

        {/* Mode selector — compact tab bar */}
        <div className="card" style={{ padding: '6px', display: 'flex', gap: '4px', borderRadius: '14px' }}>
          {[
            { id: 'template', label: 'Template' },
            { id: 'custom', label: 'Custom Prompt' },
            { id: 'gemma', label: 'AI Variations' },
          ].map(m => (
            <button key={m.id} type="button"
              onClick={() => {
                if (m.id === 'template') { setUseCustomPrompt(false); setUseGemmaVariations(false); }
                else if (m.id === 'custom') { setUseCustomPrompt(true); setUseGemmaVariations(false); }
                else { setUseGemmaVariations(true); setUseCustomPrompt(false); }
              }}
              style={{
                flex: 1, padding: '10px 16px', borderRadius: '10px', border: 'none',
                fontSize: '14px', fontWeight: mode === m.id ? 600 : 400, cursor: 'pointer',
                background: mode === m.id ? '#0071e3' : 'transparent',
                color: mode === m.id ? '#fff' : 'rgba(255,255,255,0.6)',
                transition: 'all 0.2s',
              }}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* Prompt Assistant — compact */}
        <div className="card" style={{ padding: '20px' }}>
          <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '10px' }}>Prompt Assistant</p>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              type="text"
              value={assistantDescription}
              onChange={(e) => setAssistantDescription(e.target.value)}
              placeholder="Describe what you want in plain language..."
              className="input"
              style={{ flex: 1, fontSize: '14px', padding: '10px 14px' }}
            />
            <button type="button" onClick={handleGeneratePrompt}
              disabled={isGeneratingPrompt || !assistantDescription.trim()}
              style={{
                padding: '10px 20px', borderRadius: '10px', border: 'none', fontSize: '14px',
                background: '#0071e3', color: '#fff', cursor: 'pointer', whiteSpace: 'nowrap',
                opacity: (isGeneratingPrompt || !assistantDescription.trim()) ? 0.5 : 1,
              }}>
              {isGeneratingPrompt ? 'Working...' : 'Generate'}
            </button>
          </div>
          {promptError && <p style={{ fontSize: '13px', color: '#ff6b6b', marginTop: '8px' }}>{promptError}</p>}
          {assistantPrompt && (
            <div style={{ marginTop: '12px' }}>
              <textarea value={assistantPrompt} onChange={(e) => setAssistantPrompt(e.target.value)}
                style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', color: '#f0f0f0', fontSize: '13px', height: '80px', resize: 'none', outline: 'none' }}
              />
              <button type="button" onClick={handleUsePrompt}
                style={{ marginTop: '8px', width: '100%', padding: '10px', background: 'rgba(0,113,227,0.3)', border: '1px solid #0071e3', borderRadius: '10px', color: '#2997ff', fontSize: '14px', cursor: 'pointer' }}>
                Use This Prompt
              </button>
            </div>
          )}
        </div>

        {/* Main input area — changes based on mode */}
        <div className="card" style={{ padding: '20px' }}>

          {/* Template mode */}
          {mode === 'template' && (
            <div className="space-y-4">
              <div>
                <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Template</p>
                <select value={selectedTemplate} onChange={(e) => setSelectedTemplate(e.target.value)} className="input" style={{ fontSize: '14px' }}>
                  <option value="">Choose a template...</option>
                  {templates.map((t) => (<option key={t.id} value={t.id}>{t.template_name}</option>))}
                </select>
              </div>
              {template && (
                <div style={{ padding: '12px', background: 'rgba(255,255,255,0.04)', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.06)' }}>
                  <div style={{ display: 'flex', gap: '16px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>CTR: <strong style={{ color: '#30d158' }}>{template.avg_ctr}%</strong></span>
                    <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>Cost: <strong style={{ color: '#2997ff' }}>${template.estimated_cost}</strong></span>
                    <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>Success: <strong style={{ color: '#bf5af2' }}>{template.success_rate}%</strong></span>
                  </div>
                  <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)', lineHeight: 1.5, maxHeight: '60px', overflow: 'hidden' }}>{template.prompt_base}</p>
                </div>
              )}
              <div>
                <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Refinements</p>
                <textarea value={context} onChange={(e) => setContext(e.target.value)}
                  placeholder="e.g., Focus on young families, modern home aesthetic..."
                  style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', color: '#f0f0f0', fontSize: '14px', height: '60px', resize: 'none', outline: 'none' }}
                />
              </div>
            </div>
          )}

          {/* Custom prompt mode */}
          {mode === 'custom' && (
            <div>
              <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Your Prompt</p>
              <textarea value={customPrompt} onChange={(e) => setCustomPrompt(e.target.value)}
                placeholder="Describe the image you want to generate in detail..."
                style={{ width: '100%', padding: '14px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', color: '#f0f0f0', fontSize: '14px', height: '120px', resize: 'none', outline: 'none' }}
              />
            </div>
          )}

          {/* AI Variations mode */}
          {mode === 'gemma' && (
            <div className="space-y-3">
              <p style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>Reference for AI</p>
              <textarea value={referenceInput} onChange={(e) => setReferenceInput(e.target.value)}
                placeholder="Describe the style or concept you want variations of..."
                style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', color: '#f0f0f0', fontSize: '14px', height: '70px', resize: 'none', outline: 'none' }}
              />
              <input type="file" accept="image/*" onChange={(e) => setReferenceFile(e.target.files?.[0] || null)}
                style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)' }}
              />
            </div>
          )}
        </div>

        {/* Settings row — compact horizontal */}
        <div className="card" style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
            {/* Style */}
            <div style={{ flex: '1 1 200px' }}>
              <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Style</p>
              <select value={selectedStyle} onChange={(e) => setSelectedStyle(e.target.value)} className="input" style={{ fontSize: '13px', padding: '8px 12px' }}>
                <option value="professional_photography">Professional Photography</option>
                <option value="cinematic">Cinematic</option>
                <option value="modern_illustrated">Modern Illustrated</option>
                <option value="minimalist">Minimalist</option>
                <option value="3d_render">3D Render</option>
                <option value="ghibli">Studio Ghibli</option>
                <option value="watercolor">Watercolor</option>
                <option value="anime">Anime</option>
              </select>
            </div>
            {/* Angle */}
            <div style={{ flex: '1 1 160px' }}>
              <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Angle</p>
              <select value={selectedAngle} onChange={(e) => setSelectedAngle(e.target.value)} className="input" style={{ fontSize: '13px', padding: '8px 12px' }}>
                <option value="benefit">Benefit</option>
                <option value="pain_point">Pain Point</option>
                <option value="social_proof">Social Proof</option>
                <option value="curiosity">Curiosity</option>
                <option value="urgency">Urgency</option>
              </select>
            </div>
            {/* Count */}
            <div style={{ flex: '0 0 100px' }}>
              <p style={{ fontSize: '11px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>Count</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input type="range" min="1" max="10" value={numVariations} onChange={(e) => setNumVariations(parseInt(e.target.value))}
                  style={{ flex: 1, accentColor: '#0071e3' }}
                />
                <span style={{ fontSize: '14px', fontWeight: 600, color: '#2997ff', minWidth: '24px', textAlign: 'center' }}>{numVariations}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Generate button */}
        <button type="submit"
          disabled={
            isLoading ||
            (mode === 'gemma' && !referenceInput && !referenceFile) ||
            (mode === 'custom' && !customPrompt) ||
            (mode === 'template' && !selectedTemplate)
          }
          style={{
            width: '100%', padding: '16px', borderRadius: '12px', border: 'none',
            fontSize: '17px', fontWeight: 500, cursor: 'pointer',
            background: '#0071e3', color: '#fff',
            opacity: (isLoading || (mode === 'gemma' && !referenceInput && !referenceFile) || (mode === 'custom' && !customPrompt) || (mode === 'template' && !selectedTemplate)) ? 0.5 : 1,
            transition: 'all 0.2s',
          }}>
          {isLoading ? (
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
              <span style={{ width: '16px', height: '16px', border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 1s linear infinite', display: 'inline-block' }} />
              Generating...
            </span>
          ) : (
            `Generate ${numVariations} Image${numVariations !== 1 ? 's' : ''}`
          )}
        </button>
      </form>

      <style jsx>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
