"""Landing Page Generator + Analyzer"""
import logging
import requests as http_requests
from typing import Optional
from ..config import settings
from .knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class LandingPageService:
    """Generates landing pages and analyzes existing ones"""

    @staticmethod
    async def generate_landing_page(
        vertical: str = "home_insurance",
        transcript: str = "",
        offer_url: str = "",
        target_audience: str = "",
        bonuses: list = None,
        product_name: str = "",
        product_description: str = "",
        commission: str = "",
        page_type: str = "single",
    ) -> dict:
        """Generate a complete HTML landing page that bridges an ad to an offer"""
        from google import genai

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        client = genai.Client(api_key=settings.gemini_api_key)

        offer_frameworks = KnowledgeService.get_offer_frameworks()
        compliance = KnowledgeService.get_ftc_compliance()

        bonuses_text = ""
        if bonuses:
            bonuses_text = "BONUSES TO INCLUDE:\n" + "\n".join(f"- {b}" for b in bonuses)

        transcript_block = ""
        if transcript:
            transcript_block = f"""
AD TRANSCRIPT (analyze this to understand the angle being used):
{transcript}

INSTRUCTIONS FOR TRANSCRIPT:
- Identify the emotional hook, angle, and promise used in the ad
- The landing page MUST continue the same narrative and tone
- Bridge the ad's claims to the offer — the visitor should feel continuity
"""

        offer_url_block = ""
        if offer_url:
            offer_url_block = f"""
OFFER PAGE URL: {offer_url}
- Match the offer page's theme and messaging if possible
- All CTA buttons should link to this URL
"""

        prompt = f"""You are an expert landing page designer and conversion optimizer.

Create a COMPLETE, self-contained HTML landing page for this affiliate offer.

VERTICAL: {vertical}
PRODUCT NAME: {product_name or '(derive from vertical)'}
OFFER URL: {offer_url or '#'}
COMMISSION: {commission}
TARGET AUDIENCE: {target_audience or 'General consumers'}
PAGE TYPE: {page_type}
{bonuses_text}
{transcript_block}
{offer_url_block}

VERTICAL-SPECIFIC INSTRUCTIONS:
- Use the vertical "{vertical}" to set the right tone, terminology, and design language
- Insurance verticals: professional, trust-focused, compliance-heavy
- Health verticals: benefit-driven, before/after framing, urgency
- Finance verticals: authority, savings-focused, calculator-style proof
- Opportunity verticals: aspirational, social proof heavy, income claims with disclaimers

OFFER FRAMEWORK (use Hormozi Grand Slam):
{offer_frameworks[:2000] if offer_frameworks else 'Value = Dream Outcome x Perceived Likelihood / Time Delay / Effort'}

FTC COMPLIANCE (MUST include):
{compliance[:800] if compliance else 'Include clear affiliate disclosure at the top.'}

REQUIREMENTS:
1. Single self-contained HTML file with ALL CSS written inline in a <style> tag — NO external libraries, NO Tailwind CDN, NO Bootstrap, NO frameworks. Pure HTML + CSS + vanilla JS only.
2. Mobile responsive using CSS media queries
3. Dark modern design with gradient accents, professional color palette
4. Sections: Hero with headline + CTA, Problem section, Solution section, Features/Benefits (3-5), Social proof, Guarantee, Final CTA, FTC disclosure footer
5. The affiliate link should be the CTA button href
6. Professional, high-converting design — use CSS gradients, box-shadows, border-radius for modern look
7. Include meta tags for SEO and Open Graph
8. All text must be compelling copywriting, not placeholder text
9. CSS animations for CTA buttons (subtle pulse or glow effect)
10. Zero external dependencies — the HTML file must work completely standalone
11. Include a HERO IMAGE section using a relevant free stock image from Unsplash (use <img src="https://images.unsplash.com/photo-XXXX?w=1200&h=600&fit=crop"> with a REAL Unsplash photo ID relevant to the vertical)
12. Use CSS background gradients and overlays on the hero section for dramatic effect
13. CTA buttons must have hover animations (scale + glow effect) and use contrasting bright colors (not the same as the background)
14. Include at least 2 different CTA button styles — one for the hero, one for the final section
15. Add a sticky header bar with a CTA button that appears on scroll
16. Use CSS counters or animated number sections for statistics ("500+ Happy Customers", "$2M+ Saved")
17. Add a FAQ section with expandable accordions using vanilla JS
18. The design must look like a premium SaaS landing page, NOT a generic text page
19. Use box-shadow, border-radius, and subtle gradients on every card/section for depth

Output ONLY the complete HTML code. No explanations.
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        html = response.text.strip()
        if html.startswith("```"):
            html = html.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return {
            "product": product_name or vertical,
            "page_type": page_type,
            "html": html,
        }

    @staticmethod
    async def analyze_landing_page(
        lp_url: str = "",
        lp_html: str = "",
        metrics: dict = None,
    ) -> dict:
        """Analyze a landing page and provide conversion optimization recommendations"""
        from google import genai

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        client = genai.Client(api_key=settings.gemini_api_key)

        metrics_text = ""
        if metrics:
            spend = metrics.get("spend", 0)
            lp_views = metrics.get("lp_views", 0)
            lp_clicks = metrics.get("lp_clicks", 0)
            conversions = metrics.get("conversions", 0)
            revenue = metrics.get("revenue", 0)

            lp_ctr = (lp_clicks / lp_views * 100) if lp_views > 0 else 0
            conv_rate = (conversions / lp_clicks * 100) if lp_clicks > 0 else 0
            cpa = (spend / conversions) if conversions > 0 else 0
            roas = (revenue / spend) if spend > 0 else 0

            metrics_text = f"""
PERFORMANCE METRICS:
- Spend: ${spend}
- LP Views: {lp_views}
- LP Clicks: {lp_clicks} (LP CTR: {lp_ctr:.1f}%)
- Conversions: {conversions} (Conv Rate: {conv_rate:.1f}%)
- Revenue: ${revenue}
- CPA: ${cpa:.2f}
- ROAS: {roas:.2f}x

BENCHMARKS:
- Good LP CTR: >15%
- Good Conv Rate: >3%
- Good ROAS: >2x
"""

        if lp_url:
            try:
                page_response = http_requests.get(
                    lp_url, timeout=15,
                    headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
                    allow_redirects=True, verify=False,
                )
                fetched_html = page_response.text[:8000]
                content_source = f"LANDING PAGE URL: {lp_url}\n\nFETCHED HTML CONTENT (first 8000 chars):\n{fetched_html}"
                logger.info(f"Fetched LP: {lp_url} ({len(page_response.text)} chars)")
            except Exception as fetch_err:
                logger.warning(f"Failed to fetch LP URL {lp_url}: {fetch_err}")
                content_source = f"LANDING PAGE URL: {lp_url}\n\nAnalyze this landing page based on the URL. Evaluate typical landing page elements: headline, CTA, social proof, guarantee, FTC compliance, mobile experience."
        elif lp_html:
            content_source = f"LANDING PAGE HTML:\n{lp_html[:5000]}"
        else:
            raise ValueError("Provide either lp_url or lp_html")

        prompt = f"""You are a conversion rate optimization expert. Analyze this landing page.

{content_source}
{metrics_text}

Provide a detailed analysis with:

1. OVERALL SCORE (1-10)
2. HEADLINE ANALYSIS — is it compelling? Does it address the dream outcome?
3. CTA ANALYSIS — is it visible? Above the fold? Clear action?
4. SOCIAL PROOF — present or missing? Quality?
5. GUARANTEE — present or missing? What type?
6. FTC COMPLIANCE — is affiliate disclosure present and properly placed?
7. MOBILE EXPERIENCE — responsive? Thumb-friendly CTAs?
8. CONVERSION BOTTLENECKS — what's causing visitors to leave?
9. SPECIFIC RECOMMENDATIONS — 5 actionable improvements ranked by impact
10. REWRITTEN HEADLINE — provide 3 alternative headlines

If metrics are provided, analyze them against benchmarks and identify which metric is the weakest link.

Format as clear sections with headers.
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        result = {
            "analysis": response.text,
        }
        if metrics:
            result["calculated_metrics"] = {
                "lp_ctr": round(lp_ctr, 2) if lp_views > 0 else None,
                "conversion_rate": round(conv_rate, 2) if lp_clicks > 0 else None,
                "cpa": round(cpa, 2) if conversions > 0 else None,
                "roas": round(roas, 2) if spend > 0 else None,
            }

        return result
