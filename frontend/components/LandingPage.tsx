'use client';
import { useState } from 'react';

/**
 * Public landing page. Shown when the visitor is not authenticated.
 * Click "Start free trial" or "Sign in" → caller swaps to LoginPage.
 *
 * Theme: dark cinematic (matches the rest of the dashboard so post-login
 * the visual language is unbroken).
 */
export default function LandingPage({ onCta }: { onCta: () => void }) {
  return (
    <div style={{ background: '#0a0a0c', color: '#fff', overflow: 'hidden' }}>
      <Hero onCta={onCta} />
      <WorkflowSection onCta={onCta} />
      <FeaturesBento />
      <PricingSection onCta={onCta} />
      <Footer />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hero
// ---------------------------------------------------------------------------

const HERO_VIDEO_URL =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260228_065522_522e2295-ba22-457e-8fdb-fbcd68109c73.mp4';

function Hero({ onCta }: { onCta: () => void }) {
  return (
    <section
      className="relative w-full"
      style={{ minHeight: '90vh', fontFamily: 'Barlow, sans-serif' }}
    >
      {/* Looping background video — muted, autoplay, object-cover */}
      <video
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          zIndex: 0,
        }}
      >
        <source src={HERO_VIDEO_URL} type="video/mp4" />
      </video>

      {/* Subtle dark vignette for text legibility (no flat overlay — keeps cinematic feel) */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(ellipse at center, rgba(0,0,0,0.15) 0%, rgba(0,0,0,0.45) 80%)',
          zIndex: 1,
        }}
      />

      {/* Floating nav */}
      <nav
        className="absolute left-1/2 z-20"
        style={{
          top: 24,
          transform: 'translateX(-50%)',
          width: 'min(960px, calc(100% - 32px))',
          background: 'rgba(255,255,255,0.95)',
          borderRadius: 16,
          padding: '10px 14px 10px 22px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 12px 40px rgba(0,0,0,0.18)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
        }}
      >
        <Logo />

        <div
          className="hidden md:flex items-center"
          style={{ gap: 28, fontSize: 14, fontWeight: 500, color: '#222' }}
        >
          <a href="#workflow" style={{ color: '#222' }}>About</a>
          <a href="#features" style={{ color: '#222' }}>Features</a>
          <a href="#pricing" style={{ color: '#222' }}>Pricing</a>
          <a href="#workflow" style={{ color: '#222' }}>Verticals</a>
        </div>

        <button
          onClick={onCta}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            background: '#222',
            color: '#fff',
            borderRadius: 12,
            padding: '8px 8px 8px 16px',
            fontSize: 14,
            fontWeight: 500,
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          Start Free Trial
          <span
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: '#fff',
              color: '#222',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <path d="M7 17 L17 7 M9 7 H17 V15" />
            </svg>
          </span>
        </button>
      </nav>

      {/* Hero content */}
      <div
        className="relative z-10 flex flex-col items-center justify-center text-center px-6"
        style={{ minHeight: '90vh', paddingTop: 120 }}
      >
        <h1 style={{ color: '#fff', maxWidth: 1100 }}>
          <span
            style={{
              display: 'block',
              fontFamily: 'Barlow, sans-serif',
              fontSize: 'clamp(40px, 6vw, 80px)',
              fontWeight: 500,
              letterSpacing: '-3px',
              lineHeight: 1,
            }}
          >
            Engine that turns ideas into
          </span>
          <span
            style={{
              display: 'block',
              fontFamily: '"Instrument Serif", serif',
              fontStyle: 'italic',
              fontSize: 'clamp(54px, 8.5vw, 116px)',
              fontWeight: 400,
              lineHeight: 1.04,
              marginTop: 4,
              letterSpacing: '-1px',
            }}
          >
            ad creatives that convert
          </span>
        </h1>

        <p
          style={{
            marginTop: 32,
            fontSize: 18,
            fontWeight: 500,
            fontFamily: 'Barlow, sans-serif',
            color: 'rgba(255,255,255,0.85)',
            maxWidth: 720,
            letterSpacing: '-0.2px',
          }}
        >
          AI-powered images, videos, scripts and voiceovers for affiliate
          marketers, agencies, and growth teams. 14 verticals, real Veo 3.1
          videos, ready in minutes.
        </p>

        <div className="flex flex-wrap gap-3 justify-center" style={{ marginTop: 36 }}>
          <button
            onClick={onCta}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              background: '#fff',
              color: '#0a0a0c',
              borderRadius: 999,
              padding: '14px 28px 14px 22px',
              fontSize: 16,
              fontWeight: 500,
              fontFamily: 'Barlow, sans-serif',
              boxShadow: '0 12px 32px rgba(0,0,0,0.3)',
            }}
          >
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                background: '#0a0a0c',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="#fff">
                <path d="M8 5v14l11-7z" />
              </svg>
            </span>
            See It Work
          </button>

          <button
            onClick={onCta}
            style={{
              border: '1px solid rgba(255,255,255,0.4)',
              color: '#fff',
              borderRadius: 999,
              padding: '14px 28px',
              fontSize: 16,
              fontWeight: 500,
              fontFamily: 'Barlow, sans-serif',
              background: 'rgba(255,255,255,0.06)',
              backdropFilter: 'blur(8px)',
            }}
          >
            Sign in
          </button>
        </div>

        {/* Sub-line of trust signals */}
        <p
          style={{
            marginTop: 56,
            fontSize: 12,
            color: 'rgba(255,255,255,0.55)',
            letterSpacing: '0.4px',
            textTransform: 'uppercase',
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          Powered by Veo 3.1 · Imagen 4 · DALL·E 3 · FLUX · Whisper
        </p>
      </div>
    </section>
  );
}

function Logo() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div
        style={{
          width: 30,
          height: 30,
          borderRadius: 8,
          background: 'linear-gradient(135deg, #0071e3 0%, #2997ff 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontWeight: 700,
          fontSize: 14,
          fontFamily: 'Barlow, sans-serif',
        }}
      >
        AE
      </div>
      <span
        style={{
          fontWeight: 600,
          fontSize: 16,
          color: '#222',
          fontFamily: 'Barlow, sans-serif',
          letterSpacing: '-0.3px',
        }}
      >
        Affiliate Engine
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 2 — Workflow showcase (sticky-note + cards reference)
// ---------------------------------------------------------------------------

function WorkflowSection({ onCta }: { onCta: () => void }) {
  return (
    <section
      id="workflow"
      style={{
        padding: '120px 24px',
        background:
          'radial-gradient(ellipse at top, rgba(41,151,255,0.08) 0%, rgba(10,10,12,1) 60%)',
        position: 'relative',
      }}
    >
      <div style={{ maxWidth: 1200, margin: '0 auto', position: 'relative' }}>
        {/* Floating decorations on the sides */}
        <StickyNote
          style={{
            position: 'absolute',
            top: 20,
            left: -10,
            transform: 'rotate(-6deg)',
            display: 'none',
          }}
          className="lg:block"
        />
        <DeadlineCard
          style={{
            position: 'absolute',
            top: 60,
            right: -20,
            display: 'none',
          }}
          className="lg:block"
        />

        {/* Centered headline + tagline */}
        <div style={{ textAlign: 'center', maxWidth: 760, margin: '0 auto' }}>
          <div
            style={{
              display: 'inline-block',
              padding: '6px 14px',
              borderRadius: 999,
              border: '1px solid rgba(255,255,255,0.12)',
              background: 'rgba(255,255,255,0.04)',
              fontSize: 12,
              letterSpacing: '0.5px',
              textTransform: 'uppercase',
              color: 'rgba(255,255,255,0.6)',
              marginBottom: 20,
              fontFamily: 'Barlow, sans-serif',
            }}
          >
            The end-to-end workflow
          </div>
          <h2
            style={{
              fontSize: 'clamp(36px, 5vw, 64px)',
              fontWeight: 600,
              letterSpacing: '-2px',
              lineHeight: 1.05,
              color: '#fff',
              fontFamily: 'Barlow, sans-serif',
            }}
          >
            Capture the idea, generate the creative,
            <br />
            <span
              style={{
                fontFamily: '"Instrument Serif", serif',
                fontStyle: 'italic',
                fontWeight: 400,
                color: 'rgba(255,255,255,0.7)',
              }}
            >
              ship every variant.
            </span>
          </h2>
          <p
            style={{
              marginTop: 24,
              fontSize: 17,
              color: 'rgba(255,255,255,0.6)',
              fontFamily: 'Barlow, sans-serif',
              fontWeight: 400,
            }}
          >
            One platform from research to publish. Stop juggling 7 SaaS tools.
            Stop hand-cutting Veo prompts. Generate, review, ship.
          </p>
        </div>

        {/* Active sprints + Seamless sync style cards */}
        <div
          style={{
            marginTop: 80,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: 16,
          }}
        >
          <WorkflowCard
            label="Active Sprints"
            children={
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <SprintRow tag="14" tagBg="#30d158" name="Insurance Q3" pct={80} />
                <SprintRow tag="6"  tagBg="#0071e3" name="Nutra New Hooks" pct={42} />
                <SprintRow tag="3"  tagBg="#ff453a" name="Bizop Funnel" pct={112} />
              </div>
            }
          />
          <WorkflowCard
            label="Vertical Coverage"
            children={
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {[
                  'Home Insurance', 'Health Insurance', 'Medicare',
                  'Auto', 'Life', 'CCW', 'Nutra', 'CBD',
                  'Blood Sugar', 'ED', 'Refinance', 'Home Improvement',
                  'WiFi', 'Bizop',
                ].map((v) => (
                  <span
                    key={v}
                    style={{
                      padding: '6px 12px',
                      borderRadius: 999,
                      background: 'rgba(255,255,255,0.06)',
                      border: '1px solid rgba(255,255,255,0.08)',
                      fontSize: 12,
                      color: '#e8e8ed',
                      fontFamily: 'Barlow, sans-serif',
                    }}
                  >
                    {v}
                  </span>
                ))}
              </div>
            }
          />
          <WorkflowCard
            label="Seamless Sync"
            children={
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <SyncRow icon="🎬" name="Veo 3.1" desc="Real cinematic video" />
                <SyncRow icon="🖼️" name="Imagen 4 / DALL·E 3 / FLUX" desc="14 ad-creative angles" />
                <SyncRow icon="🎙️" name="Whisper · OpenAI TTS · Lip-sync" desc="Talking-head ready" />
              </div>
            }
          />
        </div>

        <div style={{ textAlign: 'center', marginTop: 56 }}>
          <button
            onClick={onCta}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 10,
              background: '#fff',
              color: '#0a0a0c',
              padding: '14px 28px',
              borderRadius: 999,
              fontSize: 16,
              fontWeight: 500,
              fontFamily: 'Barlow, sans-serif',
            }}
          >
            Try the workflow
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </div>
    </section>
  );
}

function StickyNote({ style, className }: { style?: React.CSSProperties; className?: string }) {
  return (
    <div
      className={className}
      style={{
        width: 240,
        height: 240,
        background: '#fcef74',
        boxShadow: '0 24px 48px rgba(0,0,0,0.35)',
        padding: 28,
        fontFamily: '"Instrument Serif", serif',
        fontStyle: 'italic',
        fontSize: 22,
        color: '#1a1a1a',
        lineHeight: 1.25,
        ...style,
      }}
    >
      Capture fleeting hooks, organize creative angles, ship faster than your competitors.
    </div>
  );
}

function DeadlineCard({ style, className }: { style?: React.CSSProperties; className?: string }) {
  return (
    <div
      className={className}
      style={{
        width: 280,
        background: 'rgba(255,255,255,0.94)',
        color: '#1a1a1a',
        borderRadius: 16,
        padding: '18px 18px 22px',
        fontFamily: 'Barlow, sans-serif',
        boxShadow: '0 24px 48px rgba(0,0,0,0.35)',
        ...style,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: '#fff',
            border: '1px solid #eee',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          ⏱️
        </div>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Deadlines</span>
      </div>
      <div
        style={{
          padding: 12,
          borderRadius: 10,
          background: 'rgba(41,151,255,0.08)',
          border: '1px solid rgba(41,151,255,0.15)',
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600 }}>Q3 Variant Drop</div>
        <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>50 ads ready by Friday</div>
        <div style={{ fontSize: 12, color: '#0071e3', marginTop: 8, fontWeight: 600 }}>
          🕐 13:00 – 13:45
        </div>
      </div>
    </div>
  );
}

function WorkflowCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: 24,
        borderRadius: 18,
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <div
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: 'rgba(255,255,255,0.5)',
          letterSpacing: '0.4px',
          textTransform: 'uppercase',
          marginBottom: 18,
          fontFamily: 'Barlow, sans-serif',
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function SprintRow({ tag, tagBg, name, pct }: { tag: string; tagBg: string; name: string; pct: number }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <span
          style={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            background: tagBg,
            color: '#fff',
            fontSize: 11,
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {tag}
        </span>
        <span style={{ fontSize: 14, fontWeight: 500, color: '#e8e8ed', flex: 1 }}>{name}</span>
        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{pct}%</span>
      </div>
      <div
        style={{
          height: 4,
          borderRadius: 2,
          background: 'rgba(255,255,255,0.08)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${Math.min(pct, 100)}%`,
            background: pct > 100 ? '#ff453a' : 'linear-gradient(90deg,#0071e3,#2997ff)',
          }}
        />
      </div>
    </div>
  );
}

function SyncRow({ icon, name, desc }: { icon: string; name: string; desc: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 8,
          background: 'rgba(255,255,255,0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 18,
        }}
      >
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 500, color: '#e8e8ed' }}>{name}</div>
        <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>{desc}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 3 — Bento grid features (RIVR-style)
// ---------------------------------------------------------------------------

function FeaturesBento() {
  return (
    <section
      id="features"
      style={{
        padding: '120px 24px',
        background:
          'linear-gradient(180deg, #0a0a0c 0%, #111114 50%, #0a0a0c 100%)',
      }}
    >
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-end',
            marginBottom: 56,
            flexWrap: 'wrap',
            gap: 24,
          }}
        >
          <div style={{ maxWidth: 720 }}>
            <h2
              style={{
                fontSize: 'clamp(36px, 5vw, 56px)',
                fontWeight: 600,
                letterSpacing: '-1.5px',
                lineHeight: 1.05,
                color: '#fff',
                fontFamily: 'Barlow, sans-serif',
              }}
            >
              Architected for{' '}
              <span
                style={{
                  fontFamily: '"Instrument Serif", serif',
                  fontStyle: 'italic',
                  fontWeight: 400,
                  color: 'rgba(255,255,255,0.7)',
                }}
              >
                high-volume creative
              </span>
            </h2>
            <p
              style={{
                marginTop: 14,
                fontSize: 16,
                color: 'rgba(255,255,255,0.6)',
                fontFamily: 'Barlow, sans-serif',
              }}
            >
              Production-grade tooling. Real provider APIs. No watermarks. Cost
              tracking on every call. Audit log on every action.
            </p>
          </div>
        </div>

        {/* Bento grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gridAutoRows: 'minmax(220px, auto)',
            gap: 16,
          }}
        >
          {/* Big tile — Long-form video */}
          <BentoTile
            number="01"
            label="Long-Form Video"
            title="Chain Veo 3.1 base + 20 extensions into one polished mp4"
            body="Up to 148 seconds of cinematic AI video. Auto-stitched with ffmpeg. Cancel mid-flight, set a budget, or feed an existing image to animate from. Built on the same Veo 3.1 the big agencies pay $200/min for."
            span={{ gridColumn: 'span 2', gridRow: 'span 2', minHeight: 460 }}
            accent="🎬"
          />

          {/* Real-time yields style — Cost tracking */}
          <BentoTile
            number="02"
            label="Real Cost Tracking"
            title="Watch every cent in real time"
            body="Per-call billing from each provider's actual rate card. Zero hardcoded estimates. Filter by provider, vertical, model, or user."
          />

          {/* Bank-grade — Two-phase approval */}
          <BentoTile
            number="03"
            label="Audit-Grade Trust"
            title="Two-phase approval, full audit log"
            body="Every login, every edit, every generation recorded. Pending registrations need admin approval. Reject with a reason."
          />

          {/* Cross-chain — Multi-provider */}
          <BentoTile
            number="04"
            label="Multi-Provider"
            title="Failover across Imagen → DALL·E → FLUX → Ideogram automatically"
            body="One generation request, intelligent routing across 4+ image providers. Same for video, TTS, and transcription. Never blocked by a single vendor."
            link="View providers →"
          />

          <BentoTile
            number="05"
            label="14 Verticals"
            title="Pre-built psychology for every offer"
            body="Insurance, Nutra, ED, Bizop, Refi, Home Improvement, more. 5 conversion angles each (pain, benefit, social proof, curiosity, urgency)."
          />

          <BentoTile
            number="06"
            label="Talking Head + Lip-Sync"
            title="Portrait + script → spokesperson video in 60 seconds"
            body="Replicate-powered SadTalker, OpenAI/Google TTS, Whisper transcripts. Plug-and-play UGC."
          />
        </div>

        {/* Banner CTA — like RIVR's "Melt rigid assets into fluid yield" */}
        <div
          style={{
            marginTop: 56,
            position: 'relative',
            borderRadius: 24,
            overflow: 'hidden',
            minHeight: 320,
            background:
              'linear-gradient(135deg, #0d2748 0%, #1a4378 50%, #2a6bb8 100%)',
          }}
        >
          {/* Decorative gradient */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background:
                'radial-gradient(ellipse at 70% 50%, rgba(255,165,80,0.4) 0%, transparent 60%)',
            }}
          />

          <div
            style={{
              position: 'relative',
              padding: '56px 48px',
              display: 'flex',
              flexWrap: 'wrap',
              gap: 32,
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <div style={{ maxWidth: 540 }}>
              <h3
                style={{
                  fontSize: 'clamp(28px, 4vw, 48px)',
                  fontWeight: 600,
                  letterSpacing: '-1px',
                  lineHeight: 1.08,
                  color: '#fff',
                  fontFamily: 'Barlow, sans-serif',
                }}
              >
                Turn briefs into{' '}
                <span
                  style={{
                    fontFamily: '"Instrument Serif", serif',
                    fontStyle: 'italic',
                    fontWeight: 400,
                  }}
                >
                  conversion-ready ad sets.
                </span>
              </h3>
              <p
                style={{
                  marginTop: 14,
                  fontSize: 15,
                  color: 'rgba(255,255,255,0.8)',
                  fontFamily: 'Barlow, sans-serif',
                }}
              >
                Join the agencies and affiliate teams who stopped writing ads
                and started shipping creatives.
              </p>
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 10,
                  background: '#fff',
                  color: '#0a0a0c',
                  borderRadius: 999,
                  padding: '14px 24px',
                  fontSize: 15,
                  fontWeight: 500,
                  fontFamily: 'Barlow, sans-serif',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                  <path d="M7 17 L17 7 M9 7 H17 V15" />
                </svg>
                Launch App
              </button>
              <button
                style={{
                  border: '1px solid rgba(255,255,255,0.4)',
                  color: '#fff',
                  borderRadius: 999,
                  padding: '14px 24px',
                  fontSize: 15,
                  fontWeight: 500,
                  fontFamily: 'Barlow, sans-serif',
                  background: 'rgba(255,255,255,0.06)',
                }}
              >
                Read Docs
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function BentoTile({
  number,
  label,
  title,
  body,
  span,
  accent,
  link,
}: {
  number: string;
  label: string;
  title: string;
  body: string;
  span?: React.CSSProperties;
  accent?: string;
  link?: string;
}) {
  return (
    <div
      style={{
        position: 'relative',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 18,
        padding: 28,
        backdropFilter: 'blur(12px)',
        transition: 'all 0.3s',
        display: 'flex',
        flexDirection: 'column',
        ...span,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: '0.6px',
            textTransform: 'uppercase',
            color: 'rgba(255,255,255,0.45)',
            fontWeight: 600,
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 11,
            color: 'rgba(255,255,255,0.3)',
            fontFamily: 'monospace',
            letterSpacing: '0.2em',
          }}
        >
          {number}
        </div>
      </div>

      {accent && (
        <div
          style={{
            fontSize: 56,
            margin: '24px 0 12px',
            opacity: 0.8,
          }}
        >
          {accent}
        </div>
      )}

      <h3
        style={{
          marginTop: accent ? 0 : 24,
          fontSize: span ? 24 : 19,
          fontWeight: 600,
          color: '#fff',
          letterSpacing: '-0.5px',
          lineHeight: 1.18,
          fontFamily: 'Barlow, sans-serif',
        }}
      >
        {title}
      </h3>

      <p
        style={{
          marginTop: 12,
          fontSize: 14,
          color: 'rgba(255,255,255,0.6)',
          lineHeight: 1.5,
          fontFamily: 'Barlow, sans-serif',
          flex: 1,
        }}
      >
        {body}
      </p>

      {link && (
        <a
          href="#"
          style={{
            marginTop: 16,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 13,
            color: '#2997ff',
            fontWeight: 500,
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          {link}
        </a>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pricing
// ---------------------------------------------------------------------------

interface Tier {
  id: string;
  name: string;
  monthly: number;
  blurb: string;
  highlight?: boolean;
  features: { text: string; em?: boolean }[];
  cta: string;
}

const TIERS: Tier[] = [
  {
    id: 'starter',
    name: 'Starter',
    monthly: 79,
    blurb: 'For solo affiliates testing creative angles.',
    features: [
      { text: '100 AI ad images / month', em: true },
      { text: '5 short videos (8 sec, Veo 3.1)' },
      { text: '50 ad scripts & ad copy' },
      { text: '20 voiceovers (OpenAI / Google TTS)' },
      { text: '1 vertical' },
      { text: '1 user seat' },
      { text: 'Cost-tracked dashboard' },
      { text: 'Email support' },
    ],
    cta: 'Start free trial',
  },
  {
    id: 'growth',
    name: 'Growth',
    monthly: 399,
    blurb: 'For affiliate teams shipping multiple campaigns weekly.',
    highlight: true,
    features: [
      { text: '500 AI ad images / month', em: true },
      { text: '25 short videos (8 sec)', em: true },
      { text: '5 long videos (up to 1 min, Veo chain)' },
      { text: '10 talking-head / lip-sync videos' },
      { text: 'Unlimited scripts & ad copy' },
      { text: '100 voiceovers' },
      { text: 'Hook + transcript analyzer' },
      { text: 'All 14 verticals' },
      { text: '3 user seats' },
      { text: 'Two-phase approval workflow' },
      { text: 'Priority support' },
    ],
    cta: 'Start free trial',
  },
  {
    id: 'agency',
    name: 'Agency',
    monthly: 999,
    blurb: 'For agencies running creative for multiple brands.',
    features: [
      { text: '1500 AI ad images / month', em: true },
      { text: '50 short videos / 8 long videos' },
      { text: '30 talking-head / lip-sync videos' },
      { text: 'Everything in Growth' },
      { text: '5 user seats + multi-tenant' },
      { text: 'White-label option' },
      { text: 'API access' },
      { text: 'Custom verticals' },
      { text: 'Full audit log + admin panel' },
      { text: 'Dedicated success manager' },
    ],
    cta: 'Start free trial',
  },
];

function PricingSection({ onCta }: { onCta: () => void }) {
  const [yearly, setYearly] = useState(false);

  return (
    <section
      id="pricing"
      style={{
        padding: '120px 24px',
        background:
          'radial-gradient(ellipse at bottom, rgba(0,113,227,0.08) 0%, rgba(10,10,12,1) 60%)',
      }}
    >
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', maxWidth: 720, margin: '0 auto' }}>
          <div
            style={{
              display: 'inline-block',
              padding: '6px 14px',
              borderRadius: 999,
              border: '1px solid rgba(255,255,255,0.12)',
              background: 'rgba(255,255,255,0.04)',
              fontSize: 12,
              letterSpacing: '0.5px',
              textTransform: 'uppercase',
              color: 'rgba(255,255,255,0.6)',
              marginBottom: 20,
              fontFamily: 'Barlow, sans-serif',
            }}
          >
            Pricing
          </div>
          <h2
            style={{
              fontSize: 'clamp(36px, 5vw, 64px)',
              fontWeight: 600,
              letterSpacing: '-2px',
              lineHeight: 1.05,
              color: '#fff',
              fontFamily: 'Barlow, sans-serif',
            }}
          >
            One simple price.{' '}
            <span
              style={{
                fontFamily: '"Instrument Serif", serif',
                fontStyle: 'italic',
                fontWeight: 400,
                color: 'rgba(255,255,255,0.7)',
              }}
            >
              No surprises.
            </span>
          </h2>
          <p
            style={{
              marginTop: 18,
              fontSize: 17,
              color: 'rgba(255,255,255,0.6)',
              fontFamily: 'Barlow, sans-serif',
            }}
          >
            Each plan includes real provider compute. We track every cent —
            see exactly what you spent, where, and why.
          </p>

          {/* Billing toggle */}
          <div
            style={{
              display: 'inline-flex',
              marginTop: 32,
              padding: 4,
              borderRadius: 999,
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.08)',
            }}
          >
            <button
              onClick={() => setYearly(false)}
              style={{
                padding: '8px 20px',
                borderRadius: 999,
                fontSize: 13,
                fontWeight: 500,
                fontFamily: 'Barlow, sans-serif',
                background: !yearly ? '#fff' : 'transparent',
                color: !yearly ? '#0a0a0c' : 'rgba(255,255,255,0.6)',
                transition: 'all 0.2s',
              }}
            >
              Monthly
            </button>
            <button
              onClick={() => setYearly(true)}
              style={{
                padding: '8px 20px',
                borderRadius: 999,
                fontSize: 13,
                fontWeight: 500,
                fontFamily: 'Barlow, sans-serif',
                background: yearly ? '#fff' : 'transparent',
                color: yearly ? '#0a0a0c' : 'rgba(255,255,255,0.6)',
                transition: 'all 0.2s',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              Yearly{' '}
              <span
                style={{
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 4,
                  background: yearly ? 'rgba(48,209,88,0.15)' : 'rgba(48,209,88,0.2)',
                  color: '#30d158',
                  fontWeight: 600,
                }}
              >
                Save 20%
              </span>
            </button>
          </div>
        </div>

        <div
          style={{
            marginTop: 64,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 16,
            alignItems: 'stretch',
          }}
        >
          {TIERS.map((t) => (
            <PricingCard key={t.id} tier={t} yearly={yearly} onCta={onCta} />
          ))}
        </div>

        <div
          style={{
            marginTop: 48,
            textAlign: 'center',
            fontSize: 14,
            color: 'rgba(255,255,255,0.5)',
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          Need higher limits or on-prem?{' '}
          <a href="#" style={{ color: '#2997ff', textDecoration: 'underline' }}>
            Talk to our team
          </a>
          .
        </div>
      </div>
    </section>
  );
}

function PricingCard({
  tier,
  yearly,
  onCta,
}: {
  tier: Tier;
  yearly: boolean;
  onCta: () => void;
}) {
  const monthly = yearly ? Math.round(tier.monthly * 0.8) : tier.monthly;
  const billed = yearly ? `Billed $${monthly * 12}/yr` : 'Billed monthly';

  return (
    <div
      style={{
        position: 'relative',
        padding: 32,
        borderRadius: 20,
        background: tier.highlight
          ? 'linear-gradient(180deg, rgba(41,151,255,0.15) 0%, rgba(20,20,22,0.85) 100%)'
          : 'rgba(255,255,255,0.04)',
        border: `1px solid ${tier.highlight ? 'rgba(41,151,255,0.5)' : 'rgba(255,255,255,0.08)'}`,
        backdropFilter: 'blur(16px)',
        boxShadow: tier.highlight ? '0 24px 64px rgba(0,113,227,0.18)' : 'none',
        transform: tier.highlight ? 'translateY(-6px)' : 'none',
        transition: 'all 0.3s',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {tier.highlight && (
        <div
          style={{
            position: 'absolute',
            top: -12,
            left: '50%',
            transform: 'translateX(-50%)',
            padding: '5px 14px',
            borderRadius: 999,
            background: 'linear-gradient(90deg, #0071e3, #2997ff)',
            color: '#fff',
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.4px',
            textTransform: 'uppercase',
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          Most Popular
        </div>
      )}

      <div
        style={{
          fontSize: 13,
          fontWeight: 600,
          letterSpacing: '0.4px',
          textTransform: 'uppercase',
          color: tier.highlight ? '#2997ff' : 'rgba(255,255,255,0.5)',
          fontFamily: 'Barlow, sans-serif',
        }}
      >
        {tier.name}
      </div>

      <p
        style={{
          marginTop: 8,
          fontSize: 14,
          color: 'rgba(255,255,255,0.6)',
          fontFamily: 'Barlow, sans-serif',
          minHeight: 40,
        }}
      >
        {tier.blurb}
      </p>

      <div style={{ marginTop: 16, display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span
          style={{
            fontSize: 56,
            fontWeight: 600,
            color: '#fff',
            letterSpacing: '-2px',
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          ${monthly}
        </span>
        <span
          style={{
            fontSize: 14,
            color: 'rgba(255,255,255,0.5)',
            fontFamily: 'Barlow, sans-serif',
          }}
        >
          /mo
        </span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: 'rgba(255,255,255,0.4)',
          fontFamily: 'Barlow, sans-serif',
        }}
      >
        {billed}
      </div>

      <button
        onClick={onCta}
        style={{
          marginTop: 24,
          padding: '14px 20px',
          borderRadius: 12,
          background: tier.highlight ? '#fff' : 'rgba(255,255,255,0.08)',
          color: tier.highlight ? '#0a0a0c' : '#fff',
          border: tier.highlight ? 'none' : '1px solid rgba(255,255,255,0.15)',
          fontSize: 15,
          fontWeight: 500,
          fontFamily: 'Barlow, sans-serif',
        }}
      >
        {tier.cta}
      </button>

      <div
        style={{
          marginTop: 28,
          paddingTop: 20,
          borderTop: '1px solid rgba(255,255,255,0.08)',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        {tier.features.map((f, i) => (
          <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={tier.highlight ? '#2997ff' : '#30d158'} strokeWidth="2.5" style={{ marginTop: 2, flexShrink: 0 }}>
              <path d="M5 12l5 5L20 7" />
            </svg>
            <span
              style={{
                fontSize: 14,
                color: f.em ? '#fff' : 'rgba(255,255,255,0.7)',
                fontWeight: f.em ? 500 : 400,
                fontFamily: 'Barlow, sans-serif',
                lineHeight: 1.4,
              }}
            >
              {f.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Footer
// ---------------------------------------------------------------------------

function Footer() {
  return (
    <footer
      style={{
        padding: '64px 24px 48px',
        background: '#050507',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <div
        style={{
          maxWidth: 1200,
          margin: '0 auto',
          display: 'grid',
          gridTemplateColumns: 'minmax(220px, 2fr) repeat(3, 1fr)',
          gap: 40,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <div
              style={{
                width: 30,
                height: 30,
                borderRadius: 8,
                background: 'linear-gradient(135deg, #0071e3 0%, #2997ff 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontWeight: 700,
                fontSize: 14,
                fontFamily: 'Barlow, sans-serif',
              }}
            >
              AE
            </div>
            <span
              style={{
                fontSize: 16,
                fontWeight: 600,
                color: '#fff',
                fontFamily: 'Barlow, sans-serif',
                letterSpacing: '-0.3px',
              }}
            >
              Affiliate Engine
            </span>
          </div>
          <p
            style={{
              fontSize: 13,
              color: 'rgba(255,255,255,0.5)',
              fontFamily: 'Barlow, sans-serif',
              maxWidth: 300,
              lineHeight: 1.5,
            }}
          >
            AI-powered ad creative generation for affiliate marketers, agencies,
            and growth teams.
          </p>
        </div>

        {[
          { title: 'Product', items: ['Features', 'Pricing', 'Verticals', 'Changelog'] },
          { title: 'Resources', items: ['Documentation', 'API Reference', 'Status', 'Roadmap'] },
          { title: 'Company', items: ['About', 'Contact', 'Privacy', 'Terms'] },
        ].map((col) => (
          <div key={col.title}>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: '0.4px',
                textTransform: 'uppercase',
                color: 'rgba(255,255,255,0.4)',
                marginBottom: 14,
                fontFamily: 'Barlow, sans-serif',
              }}
            >
              {col.title}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {col.items.map((it) => (
                <a
                  key={it}
                  href="#"
                  style={{
                    fontSize: 13,
                    color: 'rgba(255,255,255,0.65)',
                    fontFamily: 'Barlow, sans-serif',
                  }}
                >
                  {it}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div
        style={{
          maxWidth: 1200,
          margin: '40px auto 0',
          paddingTop: 24,
          borderTop: '1px solid rgba(255,255,255,0.06)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
          fontSize: 12,
          color: 'rgba(255,255,255,0.4)',
          fontFamily: 'Barlow, sans-serif',
        }}
      >
        <span>© {new Date().getFullYear()} Affiliate Engine. All rights reserved.</span>
        <span>Powered by Veo 3.1, Imagen 4, DALL·E 3, FLUX, Whisper.</span>
      </div>
    </footer>
  );
}
