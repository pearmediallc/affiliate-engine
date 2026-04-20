"""Service for generating high-converting affiliate scripts using copywriting frameworks"""
import logging
from typing import Optional
import google.generativeai as genai
from ..config import settings
from .knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

# Proven copywriting frameworks
COPYWRITING_FRAMEWORKS = {
    "AIDA": {
        "name": "Attention-Interest-Desire-Action",
        "description": "Classic framework: grab attention, build interest, create desire, drive action",
        "template": """[ATTENTION] Open with surprising statistic or bold claim
[INTEREST] Explain why your audience should care
[DESIRE] Show the benefit/outcome they'll get
[ACTION] Clear CTA with urgency or incentive"""
    },
    "PAS": {
        "name": "Problem-Agitate-Solve",
        "description": "Identify problem, amplify pain, present solution",
        "template": """[PROBLEM] "Most homeowners don't know..."
[AGITATE] "This could cost you $50,000+"
[SOLVE] "Get protected in 2 minutes online"
[ACTION] "Claim Your Free Quote Now" """
    },
    "StoryBrand": {
        "name": "Hero's Journey",
        "description": "Position customer as hero, you as guide",
        "template": """[HERO] Your customer facing a challenge
[CHALLENGE] The specific problem they face
[GUIDE] How you help them succeed
[PLAN] Simple, clear steps to get what they want
[ACTION] "Click here to start your journey"
[OUTCOME] What success looks like for them"""
    },
    "SLAP": {
        "name": "Stop-Look-Act-Persuade",
        "description": "Stop scrolling, then persuade to action",
        "template": """[STOP] Controversial statement or surprising fact
[LOOK] Compelling image or stat
[ACT] Simple one-click action (Yes/No)
[PERSUADE] Social proof or guarantee"""
    },
    "BAB": {
        "name": "Before-After-Bridge",
        "description": "Contrast before/after with bridge between",
        "template": """[BEFORE] Frustrated, struggling, stuck
[AFTER] Happy, successful, protected
[BRIDGE] "Here's how to get from before to after..."
[ACTION] One simple step to transform"""
    },
    "BLOG_SEO": {
        "name": "SEO Blog Post",
        "description": "SEO-optimized blog post (1500+ words) with H2/H3 structure, keyword integration, internal linking suggestions",
        "template": """[TITLE] SEO-optimized H1 with primary keyword
[INTRO] Hook + problem statement + what the reader will learn (150 words)
[H2: Section 1] Key topic with keyword variations
[H2: Section 2] Supporting evidence, examples, data
[H2: Section 3] Practical advice / how-to steps
[H2: FAQ] 3-5 common questions with concise answers
[CONCLUSION] Summary + CTA with affiliate link placement
[INTERNAL LINKS] Suggested anchor text and topic clusters"""
    },
    "COMPARISON": {
        "name": "Product Comparison",
        "description": "Product comparison article (Product A vs B) with pros/cons table",
        "template": """[TITLE] Product A vs Product B: Which Is Better in [Year]?
[INTRO] Why this comparison matters, who it's for
[OVERVIEW TABLE] Side-by-side specs/features/pricing
[H2: Product A Deep Dive] Features, pros, cons, best for
[H2: Product B Deep Dive] Features, pros, cons, best for
[H2: Head-to-Head] Category-by-category comparison
[H2: Verdict] Clear winner recommendation with reasoning
[CTA] Affiliate links for both products"""
    },
    "LISTICLE": {
        "name": "Listicle",
        "description": "Listicle format (Top N...) with numbered items and affiliate links",
        "template": """[TITLE] Top N [Category] in [Year] (Tested & Reviewed)
[INTRO] Selection criteria, how we tested, quick picks
[#1] Best Overall - name, why, key features, price, affiliate link
[#2] Best Value - name, why, key features, price, affiliate link
[#3-N] Continue pattern with unique positioning for each
[COMPARISON TABLE] Quick-reference grid of all picks
[HOW WE CHOSE] Methodology and criteria transparency
[CTA] Final recommendation + link"""
    },
    "REVIEW": {
        "name": "Product Review",
        "description": "In-depth product review with ratings, pros/cons, verdict",
        "template": """[TITLE] [Product] Review [Year]: Honest Take After [X] Weeks
[RATING] Overall score X/10
[INTRO] What it is, who it's for, bottom line
[H2: What We Like] Detailed pros with examples
[H2: What Could Be Better] Honest cons
[H2: Features Breakdown] Key features with ratings
[H2: Pricing & Value] Cost analysis, plans comparison
[H2: Alternatives] Brief mention of 2-3 competitors
[VERDICT] Final recommendation, best for / avoid if
[CTA] Affiliate link with current deal/discount"""
    },
}

# Psychological triggers that increase conversions
PSYCHOLOGICAL_TRIGGERS = {
    "Urgency": ["Limited time", "Expires today", "Only 48 hours", "Supply running out"],
    "Scarcity": ["100% online", "No requirements", "No exams", "Instant approval"],
    "Social Proof": ["2M+ people", "98% satisfaction", "⭐⭐⭐⭐⭐", "Join thousands"],
    "Authority": ["Proven method", "Industry experts", "Certified", "Recommended by"],
    "Fear": ["Don't get caught without", "Protect yourself", "Hidden danger", "Most don't realize"],
    "Curiosity": ["You won't believe", "The #1 mistake", "Discover how", "See what others missed"],
    "Benefit": ["Save up to", "Get instant", "Completely free", "No hassle"],
    "Loss Aversion": ["Don't miss out", "You could lose", "Regret not knowing", "Act before it's gone"],
}


class ScriptGeneratorService:
    """Generates high-converting affiliate scripts using proven copywriting frameworks"""

    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            # Use the latest available model
            self.model = genai.GenerativeModel("gemini-2.5-flash")
        else:
            self.model = None
            logger.warning("Gemini not configured for script generation")

    async def generate_script(
        self,
        product: str,
        vertical: str,
        target_audience: str,
        framework: str = "PAS",
        angle: str = "benefit",
        psychological_triggers: Optional[list[str]] = None,
        include_cta: bool = True,
        desired_duration_seconds: int = 30,
    ) -> dict:
        """
        Generate a high-converting affiliate script with specific duration targeting

        Args:
            product: Product/service name
            vertical: Category (home_insurance, health, finance, etc.)
            target_audience: Who is this for? (e.g., "Homeowners over 50", "Tech-savvy millennials")
            framework: Copywriting framework (AIDA, PAS, StoryBrand, SLAP, BAB)
            angle: Psychological angle (benefit, pain_point, social_proof, curiosity, urgency)
            psychological_triggers: List of triggers to include (Urgency, Scarcity, Fear, etc.)
            include_cta: Include call-to-action
            desired_duration_seconds: Target script duration (15, 30, 60, 90, 120)

        Returns:
            Dictionary with generated script variations and duration info
        """
        if not self.model:
            raise ValueError("Gemini not configured")

        framework_info = COPYWRITING_FRAMEWORKS.get(framework, COPYWRITING_FRAMEWORKS["PAS"])

        # Build trigger list
        triggers_text = ""
        if psychological_triggers:
            selected_triggers = []
            for trigger in psychological_triggers:
                if trigger in PSYCHOLOGICAL_TRIGGERS:
                    selected_triggers.append(f"{trigger}: {PSYCHOLOGICAL_TRIGGERS[trigger][0]}")
            triggers_text = "\nInclude these psychological triggers:\n" + "\n".join(selected_triggers)

        # Duration guidelines
        duration_range = self._get_duration_range(desired_duration_seconds)

        prompt = f"""Generate 3 HIGH-CONVERTING scripts ({desired_duration_seconds} seconds) for an affiliate product.

PRODUCT: {product}
VERTICAL: {vertical}
AUDIENCE: {target_audience}
FRAMEWORK: {framework_info['name']} - {framework_info['description']}
ANGLE: {angle} (lead with {angle})
TARGET DURATION: {desired_duration_seconds} seconds ({duration_range})
INCLUDE CTA: {'Yes - end with clear call-to-action' if include_cta else 'No'}
{triggers_text}

FRAMEWORK TEMPLATE:
{framework_info['template']}

REQUIREMENTS FOR EACH SCRIPT:
- {desired_duration_seconds} seconds when read at natural pace (approximately {int(desired_duration_seconds * 2.5)} words)
- Conversational, not salesy
- Strong emotional hook in first 3-5 seconds
- Clear benefit or pain addressed
- Specific, not generic
- Includes visual cues for image/video overlay
- CTA is direct and action-oriented
- Include [TIMING: X seconds] markers for voiceover pacing

Generate 3 variations, each taking a slightly different angle or emphasis.
Label them: Script 1, Script 2, Script 3

Format as clear, easy-to-read text that can be used for:
- Video voiceover
- Social media caption
- Landing page copy
- Ad text with image overlay instructions"""

        # Inject affiliate marketing knowledge
        knowledge_context = KnowledgeService.get_context_for_script_generation()
        if knowledge_context:
            prompt = f"{knowledge_context}\n\n{prompt}"

        try:
            response = self.model.generate_content(prompt)
            script_text = response.text.strip()

            logger.info(f"Generated {desired_duration_seconds}s script for {product} using {framework} framework")

            return {
                "product": product,
                "vertical": vertical,
                "target_audience": target_audience,
                "framework": framework,
                "angle": angle,
                "desired_duration_seconds": desired_duration_seconds,
                "duration_range": duration_range,
                "scripts": script_text,
                "tips": self._get_copywriting_tips(framework, angle),
                "metadata": {
                    "format": "voiceover",
                    "pacing": "natural speech at 120-150 words per minute",
                    "estimated_word_count": int(desired_duration_seconds * 2.5),
                }
            }

        except Exception as e:
            logger.error(f"Script generation failed: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def _get_duration_range(seconds: int) -> str:
        """Get human-readable duration range"""
        if seconds <= 15:
            return "15 seconds - Short-form hooks (TikTok, Instagram Reels)"
        elif seconds <= 30:
            return "30 seconds - Standard social media (YouTube Shorts, Facebook)"
        elif seconds <= 60:
            return "60 seconds - Extended format (YouTube, mid-roll ads)"
        elif seconds <= 90:
            return "90 seconds - Premium video content"
        else:
            return "120+ seconds - Long-form sales content (landing pages, webinars)"

    async def iterate_script(
        self,
        original_script: str,
        feedback: str,
        preserve_elements: Optional[list[str]] = None,
    ) -> dict:
        """
        Iterate and improve a script based on feedback

        Args:
            original_script: The original script text
            feedback: What to improve (e.g., "More urgency", "Less salesy", "Stronger CTA")
            preserve_elements: Parts that should stay the same

        Returns:
            Improved script variation
        """
        if not self.model:
            raise ValueError("Gemini not configured")

        preserve_text = ""
        if preserve_elements:
            preserve_text = f"\nKeep these elements unchanged:\n{', '.join(preserve_elements)}"

        prompt = f"""Improve this affiliate script based on the feedback.

ORIGINAL SCRIPT:
{original_script}

FEEDBACK/IMPROVEMENT REQUEST:
{feedback}

{preserve_text}

REQUIREMENTS:
- Keep the same approximate length (30-45 seconds)
- Maintain professional tone
- Make the requested improvements clear
- Don't lose the core message
- Enhance conversion potential

Return the improved script with a brief explanation of changes made."""

        try:
            response = self.model.generate_content(prompt)
            improved_script = response.text.strip()

            logger.info("Script iteration completed")

            return {
                "original_script": original_script,
                "feedback": feedback,
                "improved_script": improved_script,
            }

        except Exception as e:
            logger.error(f"Script iteration failed: {str(e)}", exc_info=True)
            raise

    def _get_copywriting_tips(self, framework: str, angle: str) -> dict:
        """Get copywriting tips for the chosen framework and angle"""
        tips = {
            "framework_tips": {
                "PAS": "Lead with the problem, amplify the pain, then solve",
                "AIDA": "Hook attention, build interest slowly, create desire before asking for action",
                "StoryBrand": "Make the customer the hero, position yourself as guide",
                "SLAP": "Stop them mid-scroll with something unexpected",
                "BAB": "Show contrast between before and after state",
                "BLOG_SEO": "Front-load keywords in H2s, write 1500+ words, add FAQ schema",
                "COMPARISON": "Be genuinely balanced, declare a winner, use comparison tables",
                "LISTICLE": "Lead with best overall, give each item a unique positioning angle",
                "REVIEW": "Be honest about cons to build trust, include specific use-after details",
            },
            "angle_tips": {
                "benefit": "Focus on positive outcome, what they'll gain, peace of mind",
                "pain_point": "Lead with problem, what happens if they don't act, consequences",
                "social_proof": "Use numbers, testimonials, authority, 'join thousands'",
                "curiosity": "Ask questions, tease results, create knowledge gap",
                "urgency": "Limited time, running out, act now, deadline approaching",
            },
            "best_practices": [
                "First 3 seconds are critical - hook immediately",
                "Use specificity over generics (save $500 vs save money)",
                "Include visual cues for image/video placement",
                "One clear action per script - don't confuse them",
                "Speak to emotion first, logic second",
                "Use power words: instantly, guaranteed, exclusive, proven",
                "Test multiple variations - winners often surprise you",
            ],
        }
        return tips

    def get_available_frameworks(self) -> dict:
        """Get all available copywriting frameworks"""
        return COPYWRITING_FRAMEWORKS

    def get_available_triggers(self) -> dict:
        """Get all available psychological triggers"""
        return PSYCHOLOGICAL_TRIGGERS
