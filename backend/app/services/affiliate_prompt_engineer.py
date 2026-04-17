"""
Affiliate Marketing Prompt Engineering

Based on affiliate-skills methodology, generates prompts for high-converting
ad creatives using different psychological angles:
- Pain Point: Lead with the problem
- Benefit: Lead with the outcome
- Social Proof: Lead with results/numbers
- Curiosity: Lead with intrigue
- Urgency: Lead with time-sensitivity
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AffiliatePromptEngineer:
    """Generates affiliate-optimized image prompts with text overlays, CTAs, and conversion angles"""

    # Home Insurance angle-specific prompts with TEXT OVERLAYS
    HOME_INSURANCE_ANGLES = {
        "pain_point": {
            "description": "Lead with the fear/problem — what happens without protection",
            "base_prompt": """Generate a high-converting ad creative for home insurance with these specifications:

VISUAL LAYOUT:
- Split composition: LEFT half shows house damage scenario (fire, water, storm damage visible)
- RIGHT half shows protected home (secure, intact, well-maintained)
- Cinematic lighting with dramatic contrast between vulnerable (left) and protected (right)
- 1200x628px landscape, ad-ready composition

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Headline top-left: "ONE DISASTER AWAY FROM LOSING EVERYTHING" (white, 60px, bold sans-serif)
- Subtext: "Average home damage claim: $50,000+" (white, 48px, bold)
- Key stat center: "$50K+" (bright red box, 72px, bold)
- CTA bottom-right: "PROTECT YOUR HOME" (white text, green button, 54px, bold)
- Secondary: "Get Quote in 2 Minutes" (white, 32px)

COLOR SCHEME: High contrast - dark/muted left side, bright/warm right side
TONE: Urgent but empowering, not scary
STYLE: Modern digital ad, clear visual hierarchy, professional quality""",
        },
        "benefit": {
            "description": "Lead with the outcome — peace of mind, protection, relief",
            "base_prompt": """Generate a high-converting ad creative for home insurance with these specifications:

VISUAL LAYOUT:
- Happy homeowners (family or couple) enjoying their home, relaxed and content
- Interior scene: living room, kitchen, or family gathering
- Warm, golden natural lighting suggesting safety and comfort
- Beautiful, well-maintained home with modern aesthetic
- 1200x628px landscape, professional lifestyle ad style

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Main headline: "SLEEP PEACEFULLY EVERY NIGHT" (white, 64px, bold sans-serif, semi-transparent dark background)
- Subheadline: "Your home is fully protected" (white, 48px)
- Trust stat box (green): "2M+ homeowners trust us • 98% satisfaction" (white, 40px, bold)
- CTA bottom-right: "GET MY FREE QUOTE" (white text, green button, 54px, bold)
- Secondary: "No obligations • Takes 2 minutes" (white, 28px)

COLOR SCHEME: Warm tones, inviting greens and blues, professional quality
TONE: Confident, aspirational, protective
STYLE: Premium lifestyle ad, clear call-to-action, professional design""",
        },
        "social_proof": {
            "description": "Lead with results — numbers, testimonials, reviews",
            "base_prompt": """Generate a high-converting ad creative for home insurance with these specifications:

VISUAL LAYOUT:
- Composite showing diverse customer faces or customer testimonials
- Include 5-star rating graphics prominently
- Display statistics: "$500M+ Claims Paid", "9.5/10 Rating", "2M+ Customers"
- Professional grid/collage layout, well-organized
- 1200x628px landscape, ad-ready composition

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Bold headline: "2M+ HOMEOWNERS TRUST US" (white, 72px, bold sans-serif, all caps)
- Rating display: "⭐⭐⭐⭐⭐ 9.5/10 Rating" (gold/yellow box, 48px)
- Key stats: "$500M+ Claims Paid" and "98% Customer Satisfaction" (white, 48px, bold)
- Customer quote: "Finally found insurance that actually cares - Sarah M." (italic, 36px, white)
- CTA button: "SEE OUR REVIEWS" (blue button, white text, 54px)
- Secondary: "Join 2M+ Protected Homeowners" (white, 28px)

COLOR SCHEME: Trust colors - blues, golds, greens, high contrast
TONE: Trustworthy, popular, established authority
STYLE: Professional testimonial showcase, clear social proof hierarchy""",
        },
        "curiosity": {
            "description": "Lead with intrigue — unusual angle, surprising fact",
            "base_prompt": """Generate a high-converting ad creative for home insurance with these specifications:

VISUAL LAYOUT:
- Before/after or split-screen showing hidden home hazard
- Left side: revealed threat (hidden mold, electrical hazard, structural issue)
- Right side: solution/protection visualization
- Intriguing, scroll-stopping visual composition
- 1200x628px landscape, attention-grabbing ad format

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Headline: "MOST HOMEOWNERS DON'T KNOW THIS..." (white, 64px, bold sans-serif, all caps, purple box)
- Secondary: "The #1 Hidden Threat to Your Home" (white, 48px, bold)
- Alert stat: "Could Cost You $50,000+" (bright orange/red, 44px, bold)
- CTA button: "LEARN WHAT YOU'RE MISSING" (purple button, white text, 54px)
- Secondary text: "30-Second Eye-Opener" (white, 28px)

COLOR SCHEME: Attention-grabbing purples, reds, bright whites
TONE: Intriguing, educational, surprising
STYLE: Scroll-stopping ad design, clear curiosity gap, professional""",
        },
        "urgency": {
            "description": "Lead with time-sensitivity — limited offer, deadline",
            "base_prompt": """Generate a high-converting ad creative for home insurance with these specifications:

VISUAL LAYOUT:
- Action-oriented household scene or moving/settling scenario
- Include visual urgency indicators (timer, clock, or motion elements)
- Warm, energetic color palette suggesting movement and action
- Professional, confident tone (not panicked)
- 1200x628px landscape, action-focused ad composition

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Bold headline: "LIMITED TIME OFFER" (white, 64px, bold sans-serif, red/orange box, all caps)
- Main offer: "SAVE UP TO $500" (white, 56px, bold, orange box)
- Secondary offer: "+ Get Free Upgrade" (white, 48px)
- Urgency text: "Quote Locked for 48 Hours Only" (white, 44px)
- CTA button: "CLAIM OFFER NOW" (red button, white text, 54px, bold)
- Timer element: "EXPIRES IN [COUNTDOWN]" (white, 28px)
- Secondary: "Lock in your rate today" (white, 28px)

COLOR SCHEME: Hot colors - reds, oranges, bright whites, high energy
TONE: Action-oriented, time-sensitive, motivating
STYLE: Scarcity-focused ad design, clear deadline, professional urgency""",
        },
    }

    # Concealed Carry Permits angle-specific prompts
    CONCEALED_CARRY_ANGLES = {
        "benefit": {
            "description": "Lead with freedom and peace of mind",
            "base_prompt": """Generate high-converting ad creative for concealed carry permit service MATCHING WINNING IMAGE STYLE:

REAL PHOTOGRAPHY (not stock, not cartoonish):
- Photo of mature adults (50+) at actual shooting range with real equipment
- Safety glasses, hearing protection clearly visible
- Real training environment, professional setting
- Confident, capable expressions
- 1200x628px landscape format

DIRECT BENEFIT-FOCUSED TEXT OVERLAYS (bold, high contrast):
- MAIN HEADLINE: "SENIORS CAN GET CONCEALED CARRY PERMITS 100% ONLINE" (white, 56px, bold, over image)
- SUBHEADLINE: "No Classes. No Exams. No In-Person Requirements." (white, 40px)
- KEY BENEFIT BULLETS:
  • "No class requirements"
  • "No in-person exams"
  • "100% Online process"
- CTA: "CHECK ELIGIBILITY" (gold/yellow button, black text, bold)
- CREDIBILITY: Add official seal/badge for legal authority
- SECONDARY: "Fast approval • All 50 states covered"

STYLE: Professional, authoritative, matching real winning ads
PHOTOGRAPHY DIRECTION: Real mature adults, real shooting range, confident demeanor
TEXT STYLE: Bold, direct, benefit-focused (not flowery)
COLOR PALETTE: Gold accents on professional background""",
        },
        "pain_point": {
            "description": "Lead with restrictions and hassles of old system",
            "base_prompt": """Generate a high-converting ad creative for online concealed carry permits with these specifications:

VISUAL LAYOUT:
- Split screen: LEFT shows frustrated person with paperwork/bureaucracy
- RIGHT shows satisfied person with permit, relieved expression
- Dramatic contrast between complexity (left) and simplicity (right)
- Professional, empowering tone
- 1200x628px landscape, before/after style

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Headline: "TIRED OF THE BUREAUCRATIC NIGHTMARE?" (white, 60px, bold)
- Alternative: "EXHAUSTING CLASSES. CONFUSING REQUIREMENTS." (white, 56px)
- Solution text: "Get Your Permit Online in Minutes" (white, 48px)
- CTA: "SKIP THE HASSLE" (red button, white text, 54px)
- Secondary: "No In-Person Requirements" (white, 28px)

COLOR SCHEME: Contrast - muted left, bright/gold right
TONE: Empowering, solution-focused
STYLE: Problem-solution ad, clear relief narrative""",
        },
        "social_proof": {
            "description": "Lead with thousands of satisfied customers",
            "base_prompt": """Generate a high-converting ad creative for concealed carry permits with these specifications:

VISUAL LAYOUT:
- Multiple satisfied customer faces or testimonials
- 5-star rating graphics prominently displayed
- Statistics showing thousands of approved permits
- Professional testimonial format
- Diverse, trustworthy customer representation
- 1200x628px landscape

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Headline: "50,000+ PERMITS APPROVED" (white, 72px, bold, gold box)
- Rating: "⭐⭐⭐⭐⭐ 4.9/5 Stars" (gold/yellow, 48px)
- Customer testimonial: "Quick, easy, and legitimate" (italic white, 36px)
- Key stat: "98% Approval Rate" (white, 44px, bold)
- CTA: "JOIN THOUSANDS" (gold button, black text, 54px)
- Secondary: "Trusted by Responsible Gun Owners" (white, 28px)

COLOR SCHEME: Gold, black, white, trustworthy
TONE: Authoritative, popular, proven
STYLE: Social proof showcase, clear numbers, professional""",
        },
        "urgency": {
            "description": "Lead with limited-time opportunities",
            "base_prompt": """Generate a high-converting ad creative for concealed carry permits with these specifications:

VISUAL LAYOUT:
- Action-oriented scene with responsible gun owner
- Sense of opportunity and readiness
- Professional, confident demeanor
- Clear call-to-action focus
- 1200x628px landscape, action-forward composition

REQUIRED TEXT OVERLAYS (render as visible text in image):
- Bold headline: "SPECIAL OFFER - LIMITED TIME" (white, 64px, bold, red box)
- Main offer: "PROCESS YOUR PERMIT TODAY" (white, 56px, bold)
- Savings: "50% OFF Processing Fees" (gold text, 48px)
- Urgency: "Expires in 48 Hours" (white, 40px, bold)
- CTA button: "CLAIM OFFER NOW" (red button, white text, 54px)
- Secondary: "No Waiting • Instant Start" (white, 28px)

COLOR SCHEME: Gold, red, black, white, energetic
TONE: Time-sensitive, action-oriented, motivating
STYLE: Urgency-focused, clear deadline, professional scarcity""",
        },
    }

    HEALTH_INSURANCE_ANGLES = {
        "benefit": {
            "description": "Lead with health coverage and peace of mind",
            "base_prompt": """High-converting ad creative for health insurance service:
Healthy, active person enjoying wellness and protection with family.
- Active person or family engaged in healthy activities
- Doctor visit or health check scenario
- Modern healthcare facility or wellness environment
- Confident, healthy demeanor
- Professional healthcare aesthetic
- 1200x628px landscape format
- Trust and protection focused
- Professional medical quality
- Emphasizes wellness and preventive care""",
        },
        "pain_point": {
            "description": "Lead with medical costs and healthcare risks",
            "base_prompt": """Problem-focused ad for health insurance:
Contrast between uninsured medical emergency and protected with insurance.
- Split screen: worried person facing medical bills vs protected with insurance
- Hospital or medical setting visible
- Stress vs relief contrast
- Professional healthcare advertising
- 1200x628px landscape
- Emphasizes protection from unexpected costs""",
        },
        "social_proof": {
            "description": "Lead with millions covered and satisfaction",
            "base_prompt": """Social proof ad for health insurance:
Display of customer testimonials, ratings, and coverage statistics.
- Diverse satisfied customers or testimonials
- 5-star ratings prominently shown
- Coverage statistics: millions protected, high satisfaction
- Professional testimonial layout
- Trust-building design
- Professional healthcare quality""",
        },
        "urgency": {
            "description": "Lead with open enrollment and deadlines",
            "base_prompt": """Time-sensitive ad for health insurance enrollment:
Open enrollment emphasis with deadline urgency.
- Calendar or countdown timer visible
- Urgent but professional tone
- Clear deadline messaging
- Action-oriented composition
- Professional healthcare quality
- High conversion CTA""",
        },
    }

    LIFE_INSURANCE_ANGLES = {
        "benefit": {
            "description": "Lead with family protection and financial security",
            "base_prompt": """Emotional ad for life insurance:
Family enjoying secure future with protection in place.
- Happy family together: parents, children, happy moments
- Peaceful, secure home environment
- Multi-generational family representation
- Warm, protective atmosphere
- Professional lifestyle photography
- 1200x628px landscape
- Emphasizes family security and legacy""",
        },
        "pain_point": {
            "description": "Lead with financial vulnerability without coverage",
            "base_prompt": """Problem-focused life insurance ad:
Contrast between unprotected family facing hardship vs protected with insurance.
- Family or dependents facing financial stress vs security
- Before/after scenario
- Emotional vulnerability vs protection
- Professional advertising quality
- Emphasizes protection from financial ruin""",
        },
        "social_proof": {
            "description": "Lead with millions of families protected",
            "base_prompt": """Social proof for life insurance:
Display of customer testimonials and coverage statistics.
- Diverse families or individuals
- Customer testimonials about peace of mind
- Millions protected statistics
- 5-star ratings and reviews
- Professional family-focused design""",
        },
        "urgency": {
            "description": "Lead with age and health qualification windows",
            "base_prompt": """Time-sensitive life insurance ad:
Emphasize limited time for best rates based on age/health.
- Urgency around age-based rates
- Clear deadline or time-limited offer
- Professional, caring tone
- Action-oriented family focus""",
        },
    }

    AUTO_INSURANCE_ANGLES = {
        "benefit": {
            "description": "Lead with protection and peace of mind on the road",
            "base_prompt": """Positive auto insurance ad:
Safe driver or family traveling confidently with protection.
- Safe, responsible driver or family in vehicle
- Modern car on road in good conditions
- Confidence and security emphasized
- Professional automotive advertising
- 1200x628px landscape format
- Emphasizes safety and coverage""",
        },
        "pain_point": {
            "description": "Lead with accident risks and financial liability",
            "base_prompt": """Problem-focused auto insurance ad:
Risks of driving uninsured or underinsured.
- Car accident or damage scenario
- Financial consequences visible
- Legal liability emphasis
- Professional insurance quality
- Before/after protection contrast""",
        },
        "social_proof": {
            "description": "Lead with savings and customer satisfaction",
            "base_prompt": """Social proof auto insurance ad:
Display savings, discounts, and satisfied customers.
- Customers showing savings amount
- 5-star ratings and customer testimonials
- Money-back guarantee visuals
- Professional comparison charts
- Trust-building statistics""",
        },
        "urgency": {
            "description": "Lead with limited time offers and rate locks",
            "base_prompt": """Time-sensitive auto insurance ad:
Limited-time discounts or rate-lock offers.
- Countdown timer or deadline visible
- Savings amount prominent
- Action-oriented messaging
- Professional automotive quality
- Clear CTA urgency""",
        },
    }

    # Medicare Supplements - Target: 65+ seniors researching Medicare Advantage vs Medigap
    MEDICARE_ANGLES = {
        "benefit": {
            "description": "Lead with comprehensive coverage and peace of mind",
            "base_prompt": """High-converting ad for Medicare supplement plans:
Happy, active senior enjoying retirement with comprehensive healthcare coverage.
- Healthy, active senior (65+) enjoying life: traveling, with grandchildren, or exercising
- Modern healthcare facility or wellness environment optional
- Confident, secure demeanor showing peace of mind
- Professional senior lifestyle aesthetic
- 1200x628px landscape, premium quality
- TEXT OVERLAYS: "RETIREMENT WITHOUT HEALTHCARE WORRIES", "Covers What Medicare Doesn't", "Join 9M+ Seniors"
- Trust colors: blues, greens
- CTA: "GET MY COVERAGE QUOTE"
- Emphasizes: Comprehensive coverage, no gaps, trusted by millions""",
        },
        "pain_point": {
            "description": "Lead with coverage gaps and surprise medical costs",
            "base_prompt": """Problem-focused Medicare supplement ad:
Split-screen contrast between worried senior facing medical bills vs. protected with coverage.
- Left: Confused senior reviewing medical bills with calculator
- Right: Happy senior approved for comprehensive coverage
- Stress vs. relief visual contrast
- Professional healthcare quality
- 1200x628px landscape
- TEXT OVERLAYS: "MEDICARE LEAVES YOU EXPOSED", "$5,000+ OUT-OF-POCKET COSTS", "Coverage Gaps Cost Seniors $3,600/YEAR"
- CTA: "CLOSE YOUR COVERAGE GAPS"
- Colors: Warm trust colors transitioning from cautionary to relief
- Emphasizes: Hidden costs, coverage gaps, financial protection""",
        },
        "social_proof": {
            "description": "Lead with millions of seniors and expert endorsement",
            "base_prompt": """Social proof Medicare supplement ad:
Display diverse satisfied seniors, ratings, and coverage statistics.
- 3-4 satisfied senior faces with testimonials
- 5-star rating graphics (4.8+/5.0)
- Key stats: "9M+ Seniors Enrolled", "98% Satisfaction", "AEP Certified"
- Professional endorsement or expert credibility
- 1200x628px landscape
- TEXT OVERLAYS: "9 MILLION SENIORS CHOSE US", "AARP/American Medical Association Recommended", "Approved Plans: All 50 States"
- CTA: "SEE WHY SENIORS TRUST US"
- Colors: Trustworthy blues and golds
- Emphasizes: Popularity, expert approval, nationwide availability""",
        },
        "urgency": {
            "description": "Lead with AEP deadlines and age-based rates",
            "base_prompt": """Time-sensitive Medicare supplement ad:
Emphasize Annual Enrollment Period (AEP) and age-based rate locks.
- Calendar showing October-December enrollment window
- Countdown timer or deadline visualization
- Older senior (70+) next to younger senior (65-66)
- Urgent but caring professional tone
- 1200x628px landscape
- TEXT OVERLAYS: "AEP ENDS DECEMBER 7", "AGE 66? LOCK IN YOUR LOWEST RATES NOW", "After 65: Rates Increase $0.50+ Per Month"
- CTA: "ENROLL BEFORE DEADLINE"
- Colors: Warm urgent colors - golds, oranges with trust blues
- Secondary: "Open Enrollment Only Happens Once a Year"
- Emphasizes: Time-limited opportunity, age-based rate locks, annual deadline""",
        },
    }

    # Nutra (Weight Loss & Supplements) - Target: 19-50 age, 70% of Americans trying to lose weight
    NUTRA_ANGLES = {
        "benefit": {
            "description": "Lead with transformation and confidence",
            "base_prompt": """High-converting nutra supplement ad:
Before/after transformation or confident person enjoying healthy lifestyle.
- Fit, confident person in athletic/casual wear
- Or clear before/after showing dramatic transformation
- Energy, vitality, confidence emphasized
- Professional lifestyle photography
- 1200x628px landscape, aspirational quality
- TEXT OVERLAYS: "LOSE 10+ LBS IN 30 DAYS", "Finally Fit Into Those Jeans", "95% Reported Results"
- Colors: Energetic - oranges, greens, bright whites
- CTA: "START MY TRANSFORMATION"
- Meta/TikTok optimized: Before-after scroll-stopping visual
- Emphasizes: Results, transformation, confidence, speed of results""",
        },
        "pain_point": {
            "description": "Lead with frustration and failed attempts",
            "base_prompt": """Problem-focused nutra supplement ad:
Relatable struggle - person frustrated with diet/exercise not working.
- Person frustrated, tired from workouts, or disappointed with scale
- Split-screen: exhausting workout vs. easy supplement solution
- Emotional frustration vs. relief visualization
- Professional lifestyle quality
- 1200x628px landscape
- TEXT OVERLAYS: "TIRED OF DIETING & NOT LOSING WEIGHT?", "Workouts Alone Don't Cut It", "75% of Dieters Gain Weight Back"
- CTA: "TRY THE LAZY WAY"
- Colors: Frustrated tones transitioning to hopeful
- TikTok optimized: Relatable struggle first, then relief
- Emphasizes: Diet failure, workout fatigue, science-backed solution""",
        },
        "social_proof": {
            "description": "Lead with transformation results and reviews",
            "base_prompt": """Social proof nutra supplement ad:
Display customer transformations, ratings, and weight loss results.
- Grid of 4-6 before/after transformations from real customers
- 5-star ratings (4.7+/5.0) prominently
- Key stats: "847K+ Customers", "Avg. 12 LBS Lost", "98% Repurchase Rate"
- Customer testimonial quotes
- 1200x628px landscape, results showcase format
- TEXT OVERLAYS: "847,000+ TRANSFORMATIONS", "⭐4.8/5 STARS", "'I Lost 15 LBS in 6 Weeks!' - Sarah M.", "Real People. Real Results."
- CTA: "JOIN THE SUCCESS STORIES"
- Colors: Success colors - greens, golds, bright
- Meta optimized: Results wall format works well
- Emphasizes: Real customer results, popularity, transformation proof""",
        },
        "urgency": {
            "description": "Lead with limited inventory and seasonal promotions",
            "base_prompt": """Time-sensitive nutra supplement ad:
Limited-time offer with scarcity and seasonal urgency.
- Action scene - people taking supplement or active lifestyle
- Countdown timer or inventory counter visible
- Confident, energetic tone
- 1200x628px landscape
- TEXT OVERLAYS: "ONLY 347 BOTTLES LEFT", "30-DAY SUPPLY: $29.99 (Was $79)", "FREE SHAKER BOTTLE WITH ORDER", "Sale Ends Friday at Midnight"
- CTA: "GRAB YOUR SUPPLY NOW"
- Colors: Hot urgent colors - reds, oranges, bright greens
- TikTok optimized: Scarcity creates FOMO
- Secondary: "180-Day Money-Back Guarantee"
- Emphasizes: Limited stock, time-bound savings, bonus items""",
        },
    }

    # ED (Erectile Dysfunction) - Target: 40-70 men, emotional connection & authentic content
    ED_ANGLES = {
        "benefit": {
            "description": "Lead with confidence and relationship satisfaction",
            "base_prompt": """High-converting ED supplement ad:
Confident man enjoying intimate moments and relationship satisfaction.
- Attractive couple together (romantic but tasteful, not explicit)
- Man showing confidence and vitality
- Warm, intimate lighting suggesting relationship connection
- Professional yet relatable aesthetic
- 1200x628px landscape, lifestyle quality
- TEXT OVERLAYS: "RECLAIM YOUR CONFIDENCE", "Get Results in 7 Days", "Works With or Without Food"
- Colors: Warm, intimate - deep blues, oranges, romantic lighting
- CTA: "RESTORE YOUR STRENGTH"
- TikTok/Meta optimized: Emotional connection, not clinical
- Emphasizes: Confidence, relationships, quick results, natural formula""",
        },
        "pain_point": {
            "description": "Lead with embarrassment and relationship strain",
            "base_prompt": """Problem-focused ED supplement ad:
Man experiencing frustration/embarrassment, showing relationship tension.
- Man looking frustrated or avoiding intimacy
- Couple relationship strain visualization
- Emotional vulnerability clearly shown
- Professional, compassionate tone
- 1200x628px landscape
- TEXT OVERLAYS: "FEELING LESS LIKE A MAN?", "Relationships Suffer From ED", "You're Not Alone - 30M+ Men Affected"
- CTA: "TAKE BACK CONTROL"
- Colors: Serious, empathetic - deep tones transitioning to hopeful
- TikTok optimized: Authentic creator content performs better
- Emphasizes: Emotional impact, relationship importance, prevalence""",
        },
        "social_proof": {
            "description": "Lead with clinical results and verified reviews",
            "base_prompt": """Social proof ED supplement ad:
Clinical study results and verified customer reviews.
- Medical authority graphics (clinical research backgrounds)
- 5-star ratings and customer testimonials
- Key stats: "Clinically Proven", "3 Million Users", "97% Satisfaction", "FDA Compliant"
- Doctor endorsement or medical credibility
- 1200x628px landscape
- TEXT OVERLAYS: "CLINICALLY PROVEN RESULTS", "3M+ MEN TRUST US", "97% SUCCESS RATE", "FDA-Registered Facility"
- CTA: "SEE THE SCIENCE"
- Colors: Medical trust colors - blues, whites
- Meta optimized: Clinical proof and numbers
- Emphasizes: Scientific validation, doctor approval, massive user base""",
        },
        "urgency": {
            "description": "Lead with age-based rates and limited-time discounts",
            "base_prompt": """Time-sensitive ED supplement ad:
Limited-time promotion with personalized age-based urgency.
- Man showing vitality and readiness
- Clear countdown or offer expiration
- Action-oriented energy
- 1200x628px landscape
- TEXT OVERLAYS: "ANNIVERSARY SPECIAL: 60% OFF", "FREE PRIORITY SHIPPING", "Only Valid for Next 48 Hours", "Your Age = Your Discount: Age 50 = 50% Off"
- CTA: "CLAIM YOUR DISCOUNT NOW"
- Colors: Hot urgent - reds, golds, energetic
- TikTok optimized: Time-pressure drives conversions
- Secondary: "30-Day Money-Back Guarantee"
- Emphasizes: Limited-time savings, personalized offers, risk-free trial""",
        },
    }

    # Business Opportunity / Work-From-Home - Target: 18-40 age, aspiring entrepreneurs
    BIZOP_ANGLES = {
        "benefit": {
            "description": "Lead with freedom and passive income",
            "base_prompt": """High-converting bizop/WFH ad:
Young person enjoying freedom, traveling, or working from dream location.
- Person working from beach, cafe, or home office with modern aesthetic
- Laptop and freedom lifestyle emphasized
- Confident, relaxed demeanor showing financial freedom
- Aspirational but believable aesthetic
- 1200x628px landscape
- TEXT OVERLAYS: "QUIT YOUR 9-5 TODAY", "Make $5K-$10K Monthly Passively", "Work From Anywhere (Even The Beach)"
- Colors: Aspirational - bright, inspiring, tropical/modern vibes
- CTA: "START YOUR FREEDOM JOURNEY"
- TikTok optimized: Micro-influencers (5K-100K followers) perform best
- Meta optimized: Authentic creator storytelling
- Emphasizes: Freedom, passive income, location independence, speed""",
        },
        "pain_point": {
            "description": "Lead with job frustration and time poverty",
            "base_prompt": """Problem-focused bizop ad:
Person frustrated with job - tired, overworked, unfulfilled.
- Person at desk looking exhausted or trapped
- Contrast with freedom lifestyle
- Emotional burnout clearly visualized
- Split-screen: corporate trap vs. freedom
- 1200x628px landscape
- TEXT OVERLAYS: "TIRED OF WORKING FOR SOMEONE ELSE?", "69% OF WORKERS ARE UNHAPPY", "Your Boss Dictates Your Time", "There's A Better Way"
- CTA: "ESCAPE THE RAT RACE"
- Colors: Dark, confined on left; bright, free on right
- TikTok optimized: Relatable struggle, then solution
- Emphasizes: Job dissatisfaction, lack of control, burnout prevalence""",
        },
        "social_proof": {
            "description": "Lead with success stories and earnings proof",
            "base_prompt": """Social proof bizop ad:
Display multiple success stories with earnings proof.
- Grid of successful people (diverse ages/backgrounds)
- Income screenshots or earnings visuals
- 5-star ratings and testimonials
- Key stats: "47,000+ Successful Members", "$2M+ Combined Earnings", "Avg. $4,200/Month"
- Before/after success narratives
- 1200x628px landscape
- TEXT OVERLAYS: "47K+ PEOPLE EARNING PASSIVE INCOME", "⭐4.9/5 STARS", "'Made $12K in My First Month' - James M.", "See Earnings Proof Inside"
- CTA: "VIEW SUCCESS STORIES"
- Colors: Success colors - greens, golds
- Meta optimized: Social proof gallery works well
- Emphasizes: Proof of earnings, community size, member success""",
        },
        "urgency": {
            "description": "Lead with limited spots and fast action",
            "base_prompt": """Time-sensitive bizop ad:
Create urgency around limited program spots and early-bird bonuses.
- Person celebrating success or taking action
- Clock/countdown timer visual
- Energetic, action-oriented tone
- 1200x628px landscape
- TEXT OVERLAYS: "ONLY 23 SPOTS LEFT THIS MONTH", "EARLY BIRD: $500 DISCOUNT", "Free Training Ends In 2 Hours", "Act Now or Wait 30 Days"
- CTA: "RESERVE YOUR SPOT NOW"
- Colors: Hot urgent - reds, oranges, bright yellows
- TikTok optimized: FOMO and countdown drive clicks
- Secondary: "100% Money-Back Guarantee"
- Emphasizes: Limited availability, time-sensitive bonuses, fast action required""",
        },
    }

    # Home Improvement - Target: Millennials (30-45) aging into home projects
    HOME_IMPROVEMENT_ANGLES = {
        "benefit": {
            "description": "Lead with beautiful transformation and home value",
            "base_prompt": """High-converting home improvement ad:
Beautiful before/after transformation of home renovation.
- After: Stunning modern home with professional renovation
- Beautiful kitchen, bathroom, or living space transformation
- Proud homeowner enjoying the results
- Professional contractor or designer quality
- 1200x628px landscape
- TEXT OVERLAYS: "TRANSFORM YOUR HOME", "Add $50K+ to Your Home Value", "Professional Results, Affordable Price"
- Colors: Modern, inspiring - whites, warm woods, accent colors
- CTA: "START YOUR FREE CONSULTATION"
- Google/Meta optimized: Contractors actively searching
- Emphasizes: Transformation, value increase, professional quality""",
        },
        "pain_point": {
            "description": "Lead with outdated space and contractor hassles",
            "base_prompt": """Problem-focused home improvement ad:
Rundown home or outdated space showing frustration with bad contractors.
- Before: Outdated, dirty, or damaged home
- Owner looking stressed or frustrated
- Bad contractor experience visualization
- Split-screen: problem on left, solution on right
- 1200x628px landscape
- TEXT OVERLAYS: "YOUR CONTRACTORS QUIT HALFWAY?", "Stuck With Bad Contractors", "Getting Your Home Fixed Should Be Easy"
- CTA: "FIND RELIABLE CONTRACTORS"
- Colors: Dark, worn on left; bright, clean on right
- Google/Meta optimized: Millennial homeowner pain points
- Emphasizes: Contractor unreliability, outdated space, need for quality""",
        },
        "social_proof": {
            "description": "Lead with completed projects and customer reviews",
            "base_prompt": """Social proof home improvement ad:
Display completed projects and satisfied homeowner testimonials.
- Gallery of 4-6 gorgeous completed projects
- 5-star ratings (4.8+/5.0)
- Before/afters prominently featured
- Key stats: "3,200+ Projects Completed", "47K Happy Homeowners", "$2.3B in Home Value Added"
- Homeowner testimonials
- 1200x628px landscape
- TEXT OVERLAYS: "3,200+ TRANSFORMATIONS", "⭐4.8/5 STARS", "'Best Decision We Made!' - The Johnsons", "See Our Gallery"
- CTA: "VIEW RECENT PROJECTS"
- Colors: Professional, inspiring
- Google/Meta optimized: Gallery format drives consideration
- Emphasizes: Portfolio quality, customer satisfaction, transformation proof""",
        },
        "urgency": {
            "description": "Lead with seasonal promotions and financing offers",
            "base_prompt": """Time-sensitive home improvement ad:
Seasonal promotion or limited-time financing offer.
- Action scene of renovation in progress or homeowner celebrating
- Clear offer visualization (financing terms, discount amounts)
- Energetic, action-focused tone
- 1200x628px landscape
- TEXT OVERLAYS: "SPRING SPECIAL: 20% OFF", "0% APR FINANCING", "Free Design Consultation", "Offer Expires April 30"
- CTA: "GET YOUR ESTIMATE TODAY"
- Colors: Seasonal, energetic - spring pastels or warm tones
- Google optimized: Seasonal search volume peaks spring/fall
- Secondary: "Licensed & Insured • 10-Year Warranty"
- Emphasizes: Limited-time savings, financing options, professional credentials""",
        },
    }

    # Refinance Mortgages - Target: Homeowners with equity (all ages but focused on suburbs)
    REFINANCE_ANGLES = {
        "benefit": {
            "description": "Lead with lower payments and wealth building",
            "base_prompt": """High-converting refinance ad:
Happy homeowners enjoying savings or improved lifestyle.
- Family or couple in comfortable home enjoying life
- Visual of lower monthly payment or piggy bank growing
- Financial relief and freedom emphasized
- Professional lifestyle quality
- 1200x628px landscape
- TEXT OVERLAYS: "LOWER YOUR MONTHLY PAYMENT BY $200+", "Consolidate Debt While Building Equity", "Approved in 48 Hours"
- Colors: Warm, secure, trustworthy blues and greens
- CTA: "SEE YOUR SAVINGS TODAY"
- Meta/Google optimized: Financial pain-point audience
- Emphasizes: Savings, speed, debt consolidation, wealth building""",
        },
        "pain_point": {
            "description": "Lead with high rates and missed opportunities",
            "base_prompt": """Problem-focused refinance ad:
Homeowner realizing they're paying too much in interest.
- Person looking at mortgage statement with concern
- Calculator showing interest paid vs. principal
- Split-screen: overpaying left, smart refinancing right
- Professional financial quality
- 1200x628px landscape
- TEXT OVERLAYS: "PAYING $300K IN INTEREST?", "Your Rate Is 2% Higher Than Current Rates", "Refinancing Takes 48 Hours"
- CTA: "STOP OVERPAYING"
- Colors: Concerned tones transitioning to relief
- Meta optimized: Homeowner financial concerns
- Emphasizes: Interest costs, rate advantages, speed""",
        },
        "social_proof": {
            "description": "Lead with savings milestones and customer reviews",
            "base_prompt": """Social proof refinance ad:
Display customer savings, ratings, and lending credentials.
- Customer testimonials with savings amounts ($50K-$200K saved)
- 5-star ratings (4.8+/5.0)
- Key stats: "450K+ Customers", "$12B+ Savings Generated", "Licensed Lenders in All 50 States"
- Speed metrics: "Approved in 48 Hours"
- 1200x628px landscape
- TEXT OVERLAYS: "450,000+ CUSTOMERS TRUST US", "⭐4.8/5 STARS", "'Saved $127K Over Life of Loan' - Michael T.", "Average Approval Time: 48 Hours"
- CTA: "START YOUR FREE QUOTE"
- Colors: Professional lending blues and golds
- Google/Meta optimized: Trustworthy financial institution
- Emphasizes: Savings proof, speed, credentials, customer satisfaction""",
        },
        "urgency": {
            "description": "Lead with rate locks and AEP-style deadlines",
            "base_prompt": """Time-sensitive refinance ad:
Limited-time rate lock offer with urgency.
- Action scene or homeowner celebrating new approval
- Countdown timer or rate chart showing declining rates
- Motivated but professional tone
- 1200x628px landscape
- TEXT OVERLAYS: "LOCK IN 6.2% TODAY", "RATE DROP ENDS FRIDAY", "Current Rates: 6.2% (was 7.1%)", "Free Appraisal • No Closing Costs"
- CTA: "LOCK YOUR RATE NOW"
- Colors: Urgent financial colors - oranges, golds, with trust blues
- Google optimized: Rate-shopping audience
- Secondary: "Microaffiliates: 5-Minute Speed-to-Contact Wins"
- Emphasizes: Rate advantage, time-limited lock, savings potential""",
        },
    }

    # WiFi/Mesh Routers - Target: Tech-savvy homeowners (25-50) with tech homes
    WIFI_ANGLES = {
        "benefit": {
            "description": "Lead with WiFi coverage and seamless connectivity",
            "base_prompt": """High-converting WiFi mesh router ad:
Family enjoying seamless internet throughout entire home.
- Family using devices simultaneously (upstairs/downstairs)
- Modern smart home with devices connected
- Confident, satisfied expressions showing reliable connectivity
- Contemporary tech-forward aesthetic
- 1200x628px landscape
- TEXT OVERLAYS: "WIFI EVERYWHERE IN YOUR HOME", "Blazing Fast • Ultra-Reliable", "No More Dead Zones"
- Colors: Tech-forward - bright blues, sleek grays, modern accents
- CTA: "UPGRADE YOUR WIFI TODAY"
- Amazon/TikTok Shop optimized: Product-focused demonstration
- Emphasizes: Coverage, speed, reliability, modern convenience""",
        },
        "pain_point": {
            "description": "Lead with slow speeds and dead zones",
            "base_prompt": """Problem-focused WiFi ad:
Frustrated family dealing with slow internet and WiFi dead zones.
- Person struggling to connect, buffering videos, frustrated
- Multiple devices showing poor signal
- Family stress from connectivity issues
- Split-screen: bad WiFi on left, perfect connectivity on right
- 1200x628px landscape
- TEXT OVERLAYS: "TIRED OF BUFFERING?", "WiFi Not Reaching Second Floor?", "Your Router Is Obsolete"
- CTA: "SOLVE YOUR WIFI PROBLEMS"
- Colors: Frustration tones transitioning to tech success
- Meta optimized: Pain-point targeting
- Emphasizes: Speed issues, coverage gaps, obsolescence""",
        },
        "social_proof": {
            "description": "Lead with tech reviews and customer ratings",
            "base_prompt": """Social proof WiFi ad:
Expert reviews, customer ratings, and performance specs.
- Tech review logos (CNET, Wirecutter, Tom's Guide, etc.)
- 5-star ratings (4.7+/5.0) prominently
- Performance specs: Speed (AX6000+), Coverage (3000+ sqft), Device capacity (200+)
- Key stats: "847K+ Users", "TechRadar Editor's Choice", "Best Mesh Router 2026"
- 1200x628px landscape
- TEXT OVERLAYS: "FASTEST MESH ROUTER 2026", "⭐4.9/5 STARS", "Recommended by CNET & Wirecutter", "Covers 3000 SQ FT • 200+ Devices"
- CTA: "SEE REVIEWS"
- Colors: Tech-forward, professional
- Amazon/TikTok optimized: Expert credibility drives purchases
- Emphasizes: Expert endorsement, performance specs, customer ratings""",
        },
        "urgency": {
            "description": "Lead with limited-time deals and tech refresh",
            "base_prompt": """Time-sensitive WiFi ad:
Limited-time promotion or new tech release.
- Person setting up new router or enjoying upgrade
- Countdown timer or inventory indicator
- Tech-forward, action-oriented tone
- 1200x628px landscape
- TEXT OVERLAYS: "SAVE $200 TODAY", "ONLY 58 LEFT IN STOCK", "New WiFi 7 Standard • 40% Faster", "Free Professional Setup"
- CTA: "ORDER NOW"
- Colors: Tech-forward energetic - bright blues, oranges, modern
- Amazon/TikTok optimized: Scarcity drives ecommerce conversions
- Secondary: "Ships Same Day • 30-Day Returns"
- Emphasizes: Price savings, limited inventory, new technology, free setup""",
        },
    }

    # CBD/Hemp Products - Target: Health-conscious adults (25-50), wellness seekers
    CBD_ANGLES = {
        "benefit": {
            "description": "Lead with wellness and natural relief",
            "base_prompt": """High-converting CBD product ad:
Healthy, relaxed person enjoying wellness benefits.
- Person in calm, meditative setting or enjoying active lifestyle
- Natural setting (garden, yoga, wellness spa ambiance)
- Peaceful, rejuvenated expression
- Professional natural product aesthetic
- 1200x628px landscape
- TEXT OVERLAYS: "NATURALLY CALM & RELAXED", "Lab-Tested • 100% Pure Hemp", "Join 3M+ Satisfied Customers"
- Colors: Natural, calming - greens, earth tones, peaceful blues
- CTA: "DISCOVER YOUR WELLNESS"
- Organic/SEO optimized: Newsletter and organic search drive CBD sales
- Emphasizes: Natural relief, purity, wellness benefits, community""",
        },
        "pain_point": {
            "description": "Lead with stress, pain, and sleep issues",
            "base_prompt": """Problem-focused CBD ad:
Person struggling with stress, pain, or sleep issues.
- Stressed, tense person or person unable to sleep
- Split-screen: struggle on left, peaceful relief on right
- Relatable wellness challenge
- Professional natural remedy quality
- 1200x628px landscape
- TEXT OVERLAYS: "STRUGGLING WITH STRESS & ANXIETY?", "Natural Sleep Solution", "Over 30M Americans Have Sleep Issues"
- CTA: "FIND NATURAL RELIEF"
- Colors: Stressed tones transitioning to calm
- Organic/SEO optimized: Health concern searches
- Emphasizes: Common wellness challenges, natural solution""",
        },
        "social_proof": {
            "description": "Lead with lab testing and customer reviews",
            "base_prompt": """Social proof CBD ad:
Display lab certifications, customer reviews, and product quality.
- COA (Certificate of Analysis) and lab testing badges
- 5-star ratings (4.8+/5.0) prominently
- Key stats: "3M+ Users", "99.7% Pure", "Lab Tested", "180-Day Cookie Duration", "180-Day Money-Back Guarantee"
- Customer testimonials
- 1200x628px landscape
- TEXT OVERLAYS: "INDEPENDENT LAB TESTED", "⭐4.8/5 STARS", "'Finally Something That Works!' - Jessica M.", "99.7% Pure • No THC"
- CTA: "VIEW LAB RESULTS"
- Colors: Professional, trustworthy - blues, greens, clinical whites
- Organic optimized: Trust signals critical for CBD
- Emphasizes: Lab certification, purity, customer satisfaction, proof""",
        },
        "urgency": {
            "description": "Lead with limited stock and seasonal offers",
            "base_prompt": """Time-sensitive CBD ad:
Limited-time offer or seasonal wellness promotion.
- Person enjoying supplement or wellness routine
- Countdown timer or inventory counter
- Energetic but wellness-focused tone
- 1200x628px landscape
- TEXT OVERLAYS: "SPRING WELLNESS SALE: 40% OFF", "ONLY 267 BOTTLES LEFT", "Free Sample Pack with Order", "Sale Ends Sunday Midnight"
- CTA: "SHOP THE SALE"
- Colors: Seasonal wellness tones - spring pastels with nature colors
- Newsletter/Organic optimized: Email subscribers and repeat customers
- Secondary: "Free Shipping on Orders Over $50"
- Emphasizes: Limited inventory, seasonal savings, bonus items""",
        },
    }

    # Blood Sugar/Diabetes Management - Target: 35-70, health-conscious, pre-diabetic/diabetic
    BLOOD_SUGAR_ANGLES = {
        "benefit": {
            "description": "Lead with energy and healthy glucose control",
            "base_prompt": """High-converting blood sugar supplement ad:
Healthy, energetic person managing blood sugar successfully.
- Active adult enjoying life with sustained energy
- Natural, healthy lifestyle scene
- Confident, healthy demeanor showing vitality
- Professional healthcare aesthetic without clinical appearance
- 1200x628px landscape
- TEXT OVERLAYS: "STABLE ENERGY ALL DAY", "Natural Blood Sugar Support", "Clinically Proven Ingredients"
- Colors: Health-focused - greens, blues, natural earthy tones
- CTA: "TAKE CONTROL TODAY"
- Meta optimized: Health-conscious demographic
- Emphasizes: Energy stability, natural support, clinical proof""",
        },
        "pain_point": {
            "description": "Lead with diabetes risk and energy crashes",
            "base_prompt": """Problem-focused blood sugar ad:
Person struggling with energy crashes, weight gain, or pre-diabetes.
- Exhausted person, or visualization of glucose spikes/crashes
- Before/after: energy crash vs. stable energy
- Split-screen showing struggle and relief
- Professional healthcare quality
- 1200x628px landscape
- TEXT OVERLAYS: "PRE-DIABETIC? YOU'RE NOT ALONE", "Energy Crashes Are Destroying Your Health", "37M+ Americans Have Diabetes"
- CTA: "PREVENT DIABETES"
- Colors: Health concern tones transitioning to health
- Meta optimized: Health concern targeting
- Emphasizes: Disease risk, quality-of-life impact, prevalence""",
        },
        "social_proof": {
            "description": "Lead with clinical studies and diabetes specialist endorsement",
            "base_prompt": """Social proof blood sugar ad:
Display clinical study results, specialist endorsement, and patient results.
- Medical research graphics and clinical study data
- Endocrinologist or diabetes specialist credibility
- 5-star ratings (4.8+/5.0)
- Key stats: "2.1M+ Users", "Clinically Proven", "Physician Recommended", "99% Natural Ingredients"
- Patient success stories
- 1200x628px landscape
- TEXT OVERLAYS: "CLINICALLY PROVEN TO WORK", "⭐4.8/5 STARS", "Recommended by 10,000+ Doctors", "2.1M+ People Trust Us"
- CTA: "SEE CLINICAL EVIDENCE"
- Colors: Medical authority - professional blues, whites, greens
- Meta optimized: Medical credibility drives trust
- Emphasizes: Clinical validation, doctor approval, ingredient transparency""",
        },
        "urgency": {
            "description": "Lead with health windows and prevention deadline",
            "base_prompt": """Time-sensitive blood sugar ad:
Emphasize prevention window and limited-time health offer.
- Motivated person taking health action
- Calendar or age-related messaging (prevention opportunity)
- Health-focused urgency without panic
- 1200x628px landscape
- TEXT OVERLAYS: "PREDIABETIC? REVERSE IT NOW", "Prevention Window Closes Fast", "Early Action: 50% Better Outcomes", "Limited Time: $29.99 Starter Kit"
- CTA: "START PREVENTION TODAY"
- Colors: Health-focused urgent - warnings reds with health greens
- Meta optimized: Preventive health messaging
- Secondary: "60-Day Money-Back Guarantee"
- Emphasizes: Prevention opportunity, time-sensitive health intervention, affordability""",
        },
    }

    @staticmethod
    def get_angle_prompt(vertical: str, angle: str, custom_context: str = None) -> str:
        """
        Get a prompt for a specific affiliate angle

        Args:
            vertical: Vertical (e.g., "home_insurance", "concealed_carry", "medicare", "nutra", etc.)
            angle: Angle type (pain_point, benefit, social_proof, curiosity, urgency)
            custom_context: Optional custom context to add

        Returns:
            Full image generation prompt
        """
        # Select the appropriate vertical angles dictionary
        vertical_map = {
            "home_insurance": AffiliatePromptEngineer.HOME_INSURANCE_ANGLES,
            "concealed_carry": AffiliatePromptEngineer.CONCEALED_CARRY_ANGLES,
            "health_insurance": AffiliatePromptEngineer.HEALTH_INSURANCE_ANGLES,
            "life_insurance": AffiliatePromptEngineer.LIFE_INSURANCE_ANGLES,
            "auto_insurance": AffiliatePromptEngineer.AUTO_INSURANCE_ANGLES,
            "medicare": AffiliatePromptEngineer.MEDICARE_ANGLES,
            "nutra": AffiliatePromptEngineer.NUTRA_ANGLES,
            "ed": AffiliatePromptEngineer.ED_ANGLES,
            "bizop": AffiliatePromptEngineer.BIZOP_ANGLES,
            "home_improvement": AffiliatePromptEngineer.HOME_IMPROVEMENT_ANGLES,
            "refinance": AffiliatePromptEngineer.REFINANCE_ANGLES,
            "wifi": AffiliatePromptEngineer.WIFI_ANGLES,
            "cbd": AffiliatePromptEngineer.CBD_ANGLES,
            "blood_sugar": AffiliatePromptEngineer.BLOOD_SUGAR_ANGLES,
        }

        angles_dict = vertical_map.get(vertical)
        if not angles_dict:
            logger.warning(f"Unknown vertical: {vertical}. Using home_insurance defaults.")
            angles_dict = AffiliatePromptEngineer.HOME_INSURANCE_ANGLES

        # Get the angle-specific prompt
        angle_data = angles_dict.get(angle)
        if not angle_data:
            # Default to benefit angle if not found
            angle_data = angles_dict.get("benefit", {})

        prompt = angle_data.get("base_prompt", "")

        if custom_context:
            prompt += f"\n\nADDITIONAL CONTEXT: {custom_context}"

        logger.info(f"Generated affiliate prompt for {vertical}/{angle}")
        return prompt

    @staticmethod
    def get_all_angles_for_vertical(vertical: str) -> dict:
        """Get all available angles for a vertical"""
        vertical_map = {
            "home_insurance": AffiliatePromptEngineer.HOME_INSURANCE_ANGLES,
            "concealed_carry": AffiliatePromptEngineer.CONCEALED_CARRY_ANGLES,
            "health_insurance": AffiliatePromptEngineer.HEALTH_INSURANCE_ANGLES,
            "life_insurance": AffiliatePromptEngineer.LIFE_INSURANCE_ANGLES,
            "auto_insurance": AffiliatePromptEngineer.AUTO_INSURANCE_ANGLES,
            "medicare": AffiliatePromptEngineer.MEDICARE_ANGLES,
            "nutra": AffiliatePromptEngineer.NUTRA_ANGLES,
            "ed": AffiliatePromptEngineer.ED_ANGLES,
            "bizop": AffiliatePromptEngineer.BIZOP_ANGLES,
            "home_improvement": AffiliatePromptEngineer.HOME_IMPROVEMENT_ANGLES,
            "refinance": AffiliatePromptEngineer.REFINANCE_ANGLES,
            "wifi": AffiliatePromptEngineer.WIFI_ANGLES,
            "cbd": AffiliatePromptEngineer.CBD_ANGLES,
            "blood_sugar": AffiliatePromptEngineer.BLOOD_SUGAR_ANGLES,
        }

        angles_dict = vertical_map.get(vertical, {})

        return {
            angle: data["description"]
            for angle, data in angles_dict.items()
        }

    @staticmethod
    def generate_angle_variations(
        vertical: str,
        base_angle: str,
        custom_context: str = None,
        count: int = 3,
    ) -> list[str]:
        """
        Generate variations on a specific angle

        For high-converting creatives, we create subtle variations that
        test different hooks while maintaining the same angle.

        Args:
            vertical: Vertical category
            base_angle: Base angle type
            custom_context: Custom context
            count: Number of variations

        Returns:
            List of varied prompts
        """
        base_prompt = AffiliatePromptEngineer.get_angle_prompt(vertical, base_angle, custom_context)

        # For MVP, return the base prompt multiple times with slight variations
        # In production, use Gemini to create variations
        variations = [
            base_prompt,
            base_prompt.replace("professional ad style", "premium lifestyle ad"),
            base_prompt.replace("1200x628px landscape", "horizontal rectangle 1200x628px"),
        ]

        return variations[:count]
