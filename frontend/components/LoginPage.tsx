'use client';
import { useState } from 'react';
import { useAuth } from '@/lib/auth';

export default function LoginPage() {
  const { login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegister) {
        await register(email, password, fullName || undefined);
      } else {
        await login(email, password);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  if (showOnboarding) {
    return <OnboardingPage onGetStarted={() => setShowOnboarding(false)} />;
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundImage: 'url(/herobg.jpg)',
      backgroundSize: 'cover',
      backgroundPosition: 'center',
      backgroundAttachment: 'fixed',
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '24px',
    }}>
      {/* Dark overlay */}
      <div style={{
        position: 'absolute', inset: 0,
        background: 'linear-gradient(135deg, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.4) 50%, rgba(0,0,0,0.7) 100%)',
      }} />

      {/* Content container */}
      <div style={{ position: 'relative', zIndex: 1, width: '100%', maxWidth: '420px' }}>

        {/* Brand */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <h1 style={{
            fontFamily: '"SF Pro Display", -apple-system, sans-serif',
            fontSize: 'clamp(36px, 6vw, 48px)', fontWeight: 600,
            color: '#fff', lineHeight: 1.07, letterSpacing: '-0.28px',
          }}>
            Affiliate Engine
          </h1>
          <p style={{ fontSize: '17px', color: 'rgba(255,255,255,0.6)', marginTop: '8px' }}>
            AI-powered ad creative platform
          </p>
        </div>

        {/* Glass form card */}
        <div style={{
          background: 'rgba(20, 20, 22, 0.55)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          borderRadius: '16px',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          padding: 'clamp(28px, 4vw, 44px)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
        }}>
          <div style={{ marginBottom: '28px' }}>
            <h2 style={{ fontSize: '24px', fontWeight: 600, color: '#fff', lineHeight: 1.14 }}>
              {isRegister ? 'Create account' : 'Sign in'}
            </h2>
            <p style={{ fontSize: '14px', color: 'rgba(255,255,255,0.5)', marginTop: '6px' }}>
              {isRegister ? 'Start generating ad creatives' : 'Welcome back'}
            </p>
          </div>

          {error && (
            <div style={{
              padding: '12px 16px', marginBottom: '20px',
              background: 'rgba(255, 59, 48, 0.15)',
              borderLeft: '3px solid #ff3b30', borderRadius: '8px',
            }}>
              <p style={{ fontSize: '14px', color: '#ff6b6b', margin: 0 }}>{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            {isRegister && (
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.7)', marginBottom: '6px', letterSpacing: '0.3px', textTransform: 'uppercase' }}>Full Name</label>
                <input type="text" value={fullName} onChange={e => setFullName(e.target.value)} placeholder="John Doe"
                  style={{ width: '100%', padding: '12px 16px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', fontSize: '16px', color: '#fff', outline: 'none' }}
                  onFocus={e => { e.target.style.borderColor = '#0071e3'; e.target.style.background = 'rgba(255,255,255,0.12)'; }}
                  onBlur={e => { e.target.style.borderColor = 'rgba(255,255,255,0.12)'; e.target.style.background = 'rgba(255,255,255,0.08)'; }}
                />
              </div>
            )}
            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.7)', marginBottom: '6px', letterSpacing: '0.3px', textTransform: 'uppercase' }}>Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@company.com" required
                style={{ width: '100%', padding: '12px 16px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', fontSize: '16px', color: '#fff', outline: 'none' }}
                onFocus={e => { e.target.style.borderColor = '#0071e3'; e.target.style.background = 'rgba(255,255,255,0.12)'; }}
                onBlur={e => { e.target.style.borderColor = 'rgba(255,255,255,0.12)'; e.target.style.background = 'rgba(255,255,255,0.08)'; }}
              />
            </div>
            <div style={{ marginBottom: '28px' }}>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.7)', marginBottom: '6px', letterSpacing: '0.3px', textTransform: 'uppercase' }}>Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Enter password" required
                style={{ width: '100%', padding: '12px 16px', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', fontSize: '16px', color: '#fff', outline: 'none' }}
                onFocus={e => { e.target.style.borderColor = '#0071e3'; e.target.style.background = 'rgba(255,255,255,0.12)'; }}
                onBlur={e => { e.target.style.borderColor = 'rgba(255,255,255,0.12)'; e.target.style.background = 'rgba(255,255,255,0.08)'; }}
              />
            </div>
            <button type="submit" disabled={loading}
              style={{
                width: '100%', padding: '14px', fontSize: '17px', fontWeight: 500,
                background: '#0071e3', color: '#fff', border: 'none', borderRadius: '10px',
                cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
                transition: 'all 0.2s',
              }}>
              {loading ? 'Please wait...' : (isRegister ? 'Create Account' : 'Sign In')}
            </button>
          </form>

          <div style={{ textAlign: 'center', marginTop: '20px' }}>
            <button onClick={() => { setIsRegister(!isRegister); setError(''); }}
              style={{ background: 'none', border: 'none', color: '#2997ff', fontSize: '14px', cursor: 'pointer' }}>
              {isRegister ? 'Already have an account? Sign in' : "Don't have an account? Register"}
            </button>
          </div>
        </div>

        {/* Learn more link */}
        <div style={{ textAlign: 'center', marginTop: '24px' }}>
          <button
            onClick={() => setShowOnboarding(true)}
            style={{
              background: 'none', border: 'none', color: 'rgba(255,255,255,0.5)',
              fontSize: '14px', cursor: 'pointer',
            }}>
            Learn what this platform can do →
          </button>
        </div>
      </div>
    </div>
  );
}

// Inline onboarding component
function OnboardingPage({ onGetStarted }: { onGetStarted: () => void }) {
  const [currentSlide, setCurrentSlide] = useState(0);

  const slides = [
    {
      title: 'AI Image Generation',
      description: 'Generate high-converting ad creatives powered by Google Imagen 4.0 and DALL-E 3. Our AI learns from your feedback to produce better images over time.',
      features: ['Multiple provider fallback chain', 'Smart prompt assistant', 'Style customization', 'Batch generation with parallel processing'],
    },
    {
      title: 'Video Intelligence',
      description: 'Analyze any video hook from YouTube, TikTok, or Instagram. Understand what makes content convert and apply those patterns to your campaigns.',
      features: ['Hook analysis with Gemini AI', 'Transcript analysis with copywriting frameworks', 'Video downloading from 1800+ sites', 'Pattern recognition across verticals'],
    },
    {
      title: 'Script & Audio Production',
      description: 'Generate persuasive ad scripts using proven frameworks (PAS, AIDA, BAB) and convert them to professional voiceovers.',
      features: ['Multiple copywriting frameworks', 'Psychology-driven angles', 'Text-to-speech with ElevenLabs', 'Script iteration and refinement'],
    },
    {
      title: 'Self-Improving AI Engine',
      description: 'Every generation and every piece of feedback trains the system. The platform builds institutional knowledge per vertical, getting smarter with every use.',
      features: ['Automatic pattern learning', 'Per-vertical knowledge base', 'AI-generated improvement suggestions', 'Admin approval workflow'],
    },
    {
      title: 'Enterprise-Grade Controls',
      description: 'Role-based access control, per-user rate limiting, comprehensive billing tracking, and detailed analytics across all campaigns.',
      features: ['Admin, Editor, Viewer roles', 'Granular feature permissions', 'Usage tracking and billing', 'Render-ready deployment'],
    },
  ];

  const slide = slides[currentSlide];

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#000', color: '#fff', position: 'relative', overflow: 'hidden' }}>
      {/* Background image with heavy overlay */}
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: 'url(/herobg.jpg)', backgroundSize: 'cover', backgroundPosition: 'center',
        opacity: 0.3,
      }} />

      <div style={{ position: 'relative', zIndex: 1, maxWidth: '900px', margin: '0 auto', padding: '60px 24px', minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        {/* Progress dots */}
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'center', marginBottom: '48px' }}>
          {slides.map((_, i) => (
            <button key={i} onClick={() => setCurrentSlide(i)}
              style={{
                width: i === currentSlide ? '32px' : '8px', height: '8px',
                borderRadius: '4px', border: 'none', cursor: 'pointer',
                background: i === currentSlide ? '#0071e3' : 'rgba(255,255,255,0.3)',
                transition: 'all 0.3s',
              }}
            />
          ))}
        </div>

        {/* Slide content */}
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <h2 style={{
            fontFamily: '"SF Pro Display", -apple-system, sans-serif',
            fontSize: 'clamp(32px, 5vw, 56px)', fontWeight: 600, lineHeight: 1.07,
            letterSpacing: '-0.28px', marginBottom: '20px',
          }}>
            {slide.title}
          </h2>
          <p style={{
            fontSize: 'clamp(16px, 2.5vw, 21px)', color: 'rgba(255,255,255,0.7)',
            lineHeight: 1.5, maxWidth: '600px', margin: '0 auto 40px',
          }}>
            {slide.description}
          </p>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '16px', maxWidth: '700px', margin: '0 auto',
          }}>
            {slide.features.map((f, i) => (
              <div key={i} style={{
                background: 'rgba(255,255,255,0.08)', borderRadius: '12px',
                padding: '16px 20px', textAlign: 'left',
                fontSize: '14px', color: 'rgba(255,255,255,0.85)',
              }}>
                <span style={{ color: '#0071e3', marginRight: '8px' }}>+</span>{f}
              </div>
            ))}
          </div>
        </div>

        {/* Navigation */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: '16px' }}>
          {currentSlide > 0 && (
            <button onClick={() => setCurrentSlide(currentSlide - 1)}
              style={{
                padding: '12px 32px', borderRadius: '980px', fontSize: '14px',
                background: 'transparent', border: '1px solid rgba(255,255,255,0.3)',
                color: '#fff', cursor: 'pointer',
              }}>
              Back
            </button>
          )}
          {currentSlide < slides.length - 1 ? (
            <button onClick={() => setCurrentSlide(currentSlide + 1)}
              style={{
                padding: '12px 32px', borderRadius: '980px', fontSize: '14px',
                background: '#0071e3', border: 'none', color: '#fff', cursor: 'pointer',
              }}>
              Next
            </button>
          ) : (
            <button onClick={onGetStarted}
              style={{
                padding: '12px 32px', borderRadius: '980px', fontSize: '14px',
                background: '#0071e3', border: 'none', color: '#fff', cursor: 'pointer',
              }}>
              Get Started
            </button>
          )}
        </div>

        {/* Skip link */}
        <div style={{ textAlign: 'center', marginTop: '24px' }}>
          <button onClick={onGetStarted}
            style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', fontSize: '14px', cursor: 'pointer' }}>
            Skip to sign in
          </button>
        </div>
      </div>
    </div>
  );
}
