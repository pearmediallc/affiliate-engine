"""Vertical-specific templates for high-performing ad creatives"""
import uuid
from sqlalchemy.orm import Session
from ..models import Template


class VerticalTemplatesService:
    """Service for managing vertical-specific templates"""

    HOME_INSURANCE_TEMPLATES = [
        {
            "id": "home_insurance_family_safety_001",
            "vertical": "home_insurance",
            "template_name": "Family Safety - Watchful Parent",
            "description": "Parent watching children play in safe backyard - protection theme",
            "prompt_base": """Professional stock photography style image for home insurance:
Scene showing a protective parent watching happy children play in a safe, fenced backyard.
- Sunny day with clear blue sky
- Clean, well-maintained suburban backyard
- Protective parent in foreground, children playing happily
- Upscale but achievable suburban aesthetic
- Safe, fenced area clearly visible
- Happy, carefree mood
- High quality stock photo
- 1200x628px horizontal ratio
- Any text overlays must be spelled exactly as specified, character-by-character
- Warm, inviting lighting
- Professional photography quality""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 25,
            "avg_conversion_rate": 3.5,
            "success_rate": 85,
        },
        {
            "id": "home_insurance_beautiful_home_001",
            "vertical": "home_insurance",
            "template_name": "Beautiful Suburban Home",
            "description": "Stunning suburban house with protective elements - trust & security",
            "prompt_base": """Professional real estate photography for home insurance advertisement:
Beautiful suburban house showcasing security and protection.
- Large, well-maintained suburban home
- Manicured lawn and landscaping
- Beautiful front entrance
- Clear, sunny day
- Welcoming aesthetic
- Shield or protective element ready for overlay
- Professional real estate photography quality
- 1200x628px format
- Any text in image must be spelled exactly as specified
- Well-lit, attractive composition
- High-end residential neighborhood feel""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 28,
            "avg_conversion_rate": 4.0,
            "success_rate": 88,
        },
        {
            "id": "home_insurance_family_home_001",
            "vertical": "home_insurance",
            "template_name": "Happy Family at Home",
            "description": "Family enjoying time together in beautiful home - belonging & safety",
            "prompt_base": """Warm family portrait for home insurance campaign:
Happy family enjoying time together in their beautiful home.
- Multigenerational family (parents and children)
- Inside their comfortable home
- Genuine smiles and warm interaction
- Modern, well-decorated living space
- Natural lighting
- Comfortable, welcoming aesthetic
- Professional portrait quality
- 1200x628px
- No overlaid text
- Shows safety and family bonds
- Aspirational but realistic home setting""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 30,
            "avg_conversion_rate": 4.2,
            "success_rate": 90,
        },
        {
            "id": "home_insurance_couple_newlyweds_001",
            "vertical": "home_insurance",
            "template_name": "Couple with Dream Home",
            "description": "Young couple in front of beautiful new home - new beginning",
            "prompt_base": """Aspirational couple photography for home insurance:
Young couple standing in front of their beautiful new home.
- Attractive young couple
- Holding keys or in front of new home
- Beautiful suburban house in background
- Happy, excited expressions
- Professional photography quality
- Sunny day
- Upscale neighborhood
- Modern, clean aesthetic
- 1200x628px format
- Any text overlays must be spelled exactly as specified, character-by-character
- Stock photography quality
- Represents new beginning and security""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 26,
            "avg_conversion_rate": 3.8,
            "success_rate": 82,
        },
        {
            "id": "home_insurance_family_moving_001",
            "vertical": "home_insurance",
            "template_name": "Family Moving Day",
            "description": "Family unpacking in new home - fresh start & protection",
            "prompt_base": """Dynamic moving day scene for home insurance:
Happy family unpacking and settling into their new home.
- Family with moving boxes
- Bright, sunny new home interior
- Positive, hopeful mood
- Modern, spacious home interior
- Multiple family members unpacking together
- Genuine smiles and happiness
- Professional photography
- 1200x628px
- Clean, well-lit space
- Professional quality
- Shows excitement and new beginnings""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 24,
            "avg_conversion_rate": 3.6,
            "success_rate": 80,
        },
    ]

    CONCEALED_CARRY_TEMPLATES = [
        {
            "id": "concealed_carry_responsible_senior_001",
            "vertical": "concealed_carry",
            "template_name": "Responsible Senior Gun Owner",
            "description": "Professional firearms instructor or responsible senior at outdoor shooting range",
            "prompt_base": """Professional firearms advertisement image for concealed carry permit service:
Mature, responsible gun owner at safe, legal shooting range environment.
- Professional firearms instructor or gun owner (50+) in safety gear
- Outdoor shooting range or controlled training facility
- Safety glasses and hearing protection clearly visible
- Confident, lawful demeanor
- Clear bright daylight
- Professional, responsible aesthetic
- Legal, regulated environment visible
- 1200x628px landscape format
- Any text overlays must be spelled exactly as specified, character-by-character
- High quality professional photography
- Emphasizes safety and legal responsibility""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 22,
            "avg_conversion_rate": 3.2,
            "success_rate": 82,
        },
        {
            "id": "concealed_carry_freedom_symbol_001",
            "vertical": "concealed_carry",
            "template_name": "Freedom & Constitutional Rights",
            "description": "Symbolic representation of constitutional freedom and legal gun ownership",
            "prompt_base": """Symbolic image for concealed carry permit service:
Professional composition representing constitutional freedom and lawful gun ownership.
- American symbols or constitutional imagery
- Professional, dignified aesthetic
- Legal, regulated environment
- Responsible ownership emphasis
- Patriotic but not aggressive tone
- Modern professional design
- Legal and safety-focused
- 1200x628px format
- Clean, high-quality composition
- Emphasizes freedom within legal framework
- Professional advertising quality""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 24,
            "avg_conversion_rate": 3.4,
            "success_rate": 85,
        },
        {
            "id": "concealed_carry_training_class_001",
            "vertical": "concealed_carry",
            "template_name": "Professional Training Environment",
            "description": "Group training or classroom setting for concealed carry education",
            "prompt_base": """Professional training environment image for concealed carry permits:
Responsible firearms training or educational setting with multiple participants.
- Classroom or outdoor training facility
- Instructor and students in learning environment
- Safety equipment prominently displayed
- Professional, educational atmosphere
- Diverse, responsible participants
- Clear focus on training and safety
- Regulated, legal environment
- 1200x628px landscape
- Professional photography quality
- Emphasizes education and responsibility
- Confident, empowered participants""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 26,
            "avg_conversion_rate": 3.6,
            "success_rate": 87,
        },
        {
            "id": "concealed_carry_self_defense_protection_001",
            "vertical": "concealed_carry",
            "template_name": "Personal Safety & Protection",
            "description": "Emphasis on personal safety, security, and self-defense preparation",
            "prompt_base": """Personal safety and security image for concealed carry service:
Professional composition emphasizing responsible self-defense and personal protection.
- Confident, prepared individual
- Safe, controlled environment
- Professional, serious demeanor
- Emphasis on preparedness
- Legal and responsible framing
- Modern professional aesthetic
- Security and confidence emphasized
- 1200x628px format
- Clean, professional composition
- Focus on responsibility and readiness
- High-quality advertising photography""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 23,
            "avg_conversion_rate": 3.3,
            "success_rate": 84,
        },
    ]

    HEALTH_INSURANCE_TEMPLATES = [
        {
            "id": "health_insurance_active_wellness_001",
            "vertical": "health_insurance",
            "template_name": "Active & Healthy Lifestyle",
            "description": "Person or family engaged in healthy activities with medical coverage",
            "prompt_base": """Professional health insurance ad:
Active person or family enjoying wellness with healthcare protection.
- Person exercising, playing sports, or engaged in healthy activity
- Outdoor or wellness environment
- Confident, healthy demeanor
- Modern healthcare quality
- 1200x628px landscape
- Professional medical advertising
- Emphasizes preventive care and wellness""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 23,
            "avg_conversion_rate": 3.3,
            "success_rate": 83,
        },
        {
            "id": "health_insurance_family_care_001",
            "vertical": "health_insurance",
            "template_name": "Family Healthcare Protection",
            "description": "Family with healthcare coverage and peace of mind",
            "prompt_base": """Family-focused health insurance ad:
Multi-generational family with access to healthcare and protection.
- Family (parents, children, grandparents) together
- Healthcare or wellness environment
- Trust and protection emphasized
- Professional family healthcare quality
- 1200x628px landscape
- Warmth and security focused""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 25,
            "avg_conversion_rate": 3.5,
            "success_rate": 85,
        },
        {
            "id": "health_insurance_doctor_visit_001",
            "vertical": "health_insurance",
            "template_name": "Professional Medical Care",
            "description": "Patient receiving professional medical care with insurance coverage",
            "prompt_base": """Medical professional health insurance ad:
Patient receiving healthcare from professional doctor in modern facility.
- Doctor and patient interaction in healthcare setting
- Modern medical facility or clinic
- Professional, trustworthy atmosphere
- High-quality medical photography
- 1200x628px landscape
- Emphasizes access to professional care""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 24,
            "avg_conversion_rate": 3.4,
            "success_rate": 84,
        },
    ]

    LIFE_INSURANCE_TEMPLATES = [
        {
            "id": "life_insurance_family_security_001",
            "vertical": "life_insurance",
            "template_name": "Family Security & Future",
            "description": "Happy family with financial protection and peace of mind",
            "prompt_base": """Emotional life insurance ad:
Family enjoying secure future with financial protection.
- Happy family moments together
- Home or family gathering setting
- Multi-generational (parents, children, possibly grandparents)
- Warm, secure, peaceful atmosphere
- Professional lifestyle photography
- 1200x628px landscape
- Emphasizes family legacy and security""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 26,
            "avg_conversion_rate": 3.6,
            "success_rate": 86,
        },
        {
            "id": "life_insurance_financial_planning_001",
            "vertical": "life_insurance",
            "template_name": "Financial Planning & Protection",
            "description": "Professional discussing financial security and life coverage",
            "prompt_base": """Financial planning life insurance ad:
Professional meeting with client about financial security.
- Advisor and client in professional setting
- Financial planning documents or charts
- Trust and expertise emphasized
- Modern office environment
- Professional business photography
- 1200x628px landscape
- Emphasizes professional guidance""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 22,
            "avg_conversion_rate": 3.2,
            "success_rate": 82,
        },
    ]

    AUTO_INSURANCE_TEMPLATES = [
        {
            "id": "auto_insurance_safe_driver_001",
            "vertical": "auto_insurance",
            "template_name": "Safe Driving Coverage",
            "description": "Responsible driver or family traveling with insurance protection",
            "prompt_base": """Safety-focused auto insurance ad:
Confident driver or family in safe vehicle with protection.
- Driver or family in modern, safe vehicle
- Road or driving scenario
- Clear, good driving conditions
- Confidence and security emphasized
- Professional automotive photography
- 1200x628px landscape
- Modern car interior or exterior""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 23,
            "avg_conversion_rate": 3.3,
            "success_rate": 84,
        },
        {
            "id": "auto_insurance_savings_001",
            "vertical": "auto_insurance",
            "template_name": "Affordable Coverage & Savings",
            "description": "Driver with savings highlights and cost-effective insurance",
            "prompt_base": """Value-focused auto insurance ad:
Display of savings, discounts, and affordable coverage options.
- Driver with vehicle showing savings or discount badges
- Money-saving highlights visible
- Professional automotive quality
- Trust and affordability emphasized
- 1200x628px landscape
- Clear value proposition""",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 24,
            "avg_conversion_rate": 3.4,
            "success_rate": 85,
        },
    ]

    MEDICARE_TEMPLATES = [
        {
            "id": "medicare_comprehensive_coverage_001",
            "vertical": "medicare",
            "template_name": "Comprehensive Medicare Coverage",
            "description": "Active senior with complete coverage peace of mind",
            "prompt_base": "Happy senior enjoying retirement with comprehensive Medicare supplement coverage. Shows security, wellness, and family time. 1200x628px landscape format.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 28,
            "avg_conversion_rate": 4.1,
            "success_rate": 87,
        },
        {
            "id": "medicare_aep_enrollment_001",
            "vertical": "medicare",
            "template_name": "Annual Enrollment Period (AEP)",
            "description": "Urgent AEP messaging with deadline and rate lock emphasis",
            "prompt_base": "Medicare supplement AEP enrollment visualization with calendar, deadline, and rate lock messaging. Shows October-December enrollment window urgency. Professional healthcare quality.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 32,
            "avg_conversion_rate": 4.5,
            "success_rate": 89,
        },
    ]

    NUTRA_TEMPLATES = [
        {
            "id": "nutra_transformation_001",
            "vertical": "nutra",
            "template_name": "Weight Loss Transformation",
            "description": "Before/after transformation showcasing results",
            "prompt_base": "Dramatic weight loss transformation before/after. Shows fit person enjoying confidence. Results-focused, aspirational quality. 1200x628px landscape.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 35,
            "avg_conversion_rate": 5.2,
            "success_rate": 92,
        },
        {
            "id": "nutra_rapid_results_001",
            "vertical": "nutra",
            "template_name": "Rapid Results (30-60 Days)",
            "description": "Fast results messaging appealing to impatient buyers",
            "prompt_base": "Before/after showing rapid 30-60 day transformation. Large text overlays emphasizing speed. High-energy, results-focused aesthetic. Strong CTA for quick action.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 38,
            "avg_conversion_rate": 5.5,
            "success_rate": 93,
        },
    ]

    ED_TEMPLATES = [
        {
            "id": "ed_confidence_001",
            "vertical": "ed",
            "template_name": "Confidence & Relationship",
            "description": "Intimate couple showing confidence and relationship satisfaction",
            "prompt_base": "Confident man with satisfied partner, showing relationship intimacy and trust. Warm, tasteful lighting. Relationship-focused, emotional connection emphasized. Professional quality.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 26,
            "avg_conversion_rate": 3.8,
            "success_rate": 85,
        },
        {
            "id": "ed_clinical_results_001",
            "vertical": "ed",
            "template_name": "Clinical Proof & Results",
            "description": "Medical credibility with study results and doctor endorsement",
            "prompt_base": "Clinical research graphics, doctor endorsement, and verified customer results. Medical authority and scientific proof emphasized. Professional healthcare quality.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 24,
            "avg_conversion_rate": 3.5,
            "success_rate": 82,
        },
    ]

    BIZOP_TEMPLATES = [
        {
            "id": "bizop_freedom_001",
            "vertical": "bizop",
            "template_name": "Location Freedom & Lifestyle",
            "description": "Young entrepreneur enjoying beach lifestyle working remotely",
            "prompt_base": "Person working from beautiful location (beach, cafe, mountain). Laptop visible, relaxed confident demeanor. Freedom and lifestyle emphasized. Aspirational quality. 1200x628px.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 32,
            "avg_conversion_rate": 4.8,
            "success_rate": 88,
        },
        {
            "id": "bizop_income_proof_001",
            "vertical": "bizop",
            "template_name": "Income Proof & Success Stories",
            "description": "Display of earnings, success stories, and community validation",
            "prompt_base": "Grid of successful entrepreneurs with income screenshots. 5-star ratings, testimonials. Success visual hierarchy. Proof-of-earnings gallery format. Professional quality.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 28,
            "avg_conversion_rate": 4.2,
            "success_rate": 86,
        },
    ]

    HOME_IMPROVEMENT_TEMPLATES = [
        {
            "id": "home_improvement_transformation_001",
            "vertical": "home_improvement",
            "template_name": "Kitchen/Bathroom Transformation",
            "description": "Stunning before/after home renovation showcase",
            "prompt_base": "Beautiful before/after renovation of kitchen or bathroom. After shows professional quality design. Proud homeowner enjoying results. Aspirational home design quality. 1200x628px.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 29,
            "avg_conversion_rate": 4.3,
            "success_rate": 87,
        },
        {
            "id": "home_improvement_contractor_trust_001",
            "vertical": "home_improvement",
            "template_name": "Reliable Contractor Selection",
            "description": "Professional contractor team credibility and portfolio",
            "prompt_base": "Professional contractor team in action, completed project photos gallery. Before/afters prominently displayed. Trust, professionalism, quality emphasized. Portfolio-gallery format.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.03,
            "avg_ctr": 26,
            "avg_conversion_rate": 3.9,
            "success_rate": 84,
        },
    ]

    REFINANCE_TEMPLATES = [
        {
            "id": "refinance_savings_001",
            "vertical": "refinance",
            "template_name": "Monthly Savings Visualization",
            "description": "Show tangible monthly payment reduction benefits",
            "prompt_base": "Visual comparison of monthly payments before/after refinance. Savings amount prominently displayed. Happy homeowner enjoying financial relief. Professional financial quality. 1200x628px.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 27,
            "avg_conversion_rate": 4.0,
            "success_rate": 85,
        },
        {
            "id": "refinance_rate_lock_001",
            "vertical": "refinance",
            "template_name": "Rate Lock Urgency Offer",
            "description": "Limited-time rate lock with deadline emphasis",
            "prompt_base": "Rate comparison chart showing current rates vs. competitor rates. Countdown timer or deadline visible. Rate lock offer emphasized. Urgent financial quality. Professional mortgage aesthetic.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 31,
            "avg_conversion_rate": 4.6,
            "success_rate": 88,
        },
    ]

    WIFI_TEMPLATES = [
        {
            "id": "wifi_coverage_001",
            "vertical": "wifi",
            "template_name": "Whole Home WiFi Coverage",
            "description": "Family enjoying seamless connectivity throughout home",
            "prompt_base": "Family using devices simultaneously in different rooms (upstairs/downstairs). All devices connected seamlessly. Modern smart home aesthetic. Professional tech quality. 1200x628px.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 26,
            "avg_conversion_rate": 3.9,
            "success_rate": 84,
        },
        {
            "id": "wifi_speed_performance_001",
            "vertical": "wifi",
            "template_name": "Speed & Performance Specs",
            "description": "Technical specs and performance benchmarks showcase",
            "prompt_base": "Speed metrics, performance graphs, WiFi 7 technology visualization. Expert review badges (CNET, Wirecutter). Specs prominently displayed. Tech-forward professional quality.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 23,
            "avg_conversion_rate": 3.5,
            "success_rate": 81,
        },
    ]

    CBD_TEMPLATES = [
        {
            "id": "cbd_wellness_001",
            "vertical": "cbd",
            "template_name": "Natural Wellness & Relief",
            "description": "Relaxed person enjoying natural health benefits",
            "prompt_base": "Peaceful person in meditation or wellness setting. Natural product aesthetic with hemp/plant imagery. Calm, rejuvenated expression. Professional natural remedy quality. 1200x628px landscape.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 24,
            "avg_conversion_rate": 3.6,
            "success_rate": 83,
        },
        {
            "id": "cbd_lab_certified_001",
            "vertical": "cbd",
            "template_name": "Lab-Tested & Certified Quality",
            "description": "Lab certification badges and purity verification",
            "prompt_base": "COA (Certificate of Analysis) graphics, lab testing badges, purity certifications. Professional laboratory quality. Trust-building credibility emphasis. 1200x628px.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 22,
            "avg_conversion_rate": 3.3,
            "success_rate": 80,
        },
    ]

    BLOOD_SUGAR_TEMPLATES = [
        {
            "id": "blood_sugar_energy_001",
            "vertical": "blood_sugar",
            "template_name": "Stable Energy & Vitality",
            "description": "Active person enjoying sustained energy throughout day",
            "prompt_base": "Active adult with sustained energy, healthy vitality. Natural wellness setting. Confident, healthy demeanor. Professional healthcare quality without clinical appearance. 1200x628px.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 25,
            "avg_conversion_rate": 3.7,
            "success_rate": 84,
        },
        {
            "id": "blood_sugar_clinical_001",
            "vertical": "blood_sugar",
            "template_name": "Clinically Proven Formula",
            "description": "Medical research validation and doctor endorsement",
            "prompt_base": "Clinical study graphics, endocrinologist credibility, research data visualization. Medical authority and scientific proof. Professional healthcare quality. 1200x628px.",
            "width": 1200,
            "height": 628,
            "estimated_cost": 0.02,
            "avg_ctr": 23,
            "avg_conversion_rate": 3.4,
            "success_rate": 82,
        },
    ]

    @staticmethod
    def get_home_insurance_templates(db: Session) -> list[Template]:
        """Get all home insurance templates from database"""
        return db.query(Template).filter(
            Template.vertical == "home_insurance",
            Template.is_active == True
        ).all()

    @staticmethod
    def get_template_by_id(db: Session, template_id: str) -> Template:
        """Get a specific template"""
        return db.query(Template).filter(Template.id == template_id).first()

    @staticmethod
    def initialize_default_templates(db: Session):
        """Initialize default templates for all verticals if they don't exist"""
        all_templates = (
            VerticalTemplatesService.HOME_INSURANCE_TEMPLATES +
            VerticalTemplatesService.CONCEALED_CARRY_TEMPLATES +
            VerticalTemplatesService.HEALTH_INSURANCE_TEMPLATES +
            VerticalTemplatesService.LIFE_INSURANCE_TEMPLATES +
            VerticalTemplatesService.AUTO_INSURANCE_TEMPLATES +
            VerticalTemplatesService.MEDICARE_TEMPLATES +
            VerticalTemplatesService.NUTRA_TEMPLATES +
            VerticalTemplatesService.ED_TEMPLATES +
            VerticalTemplatesService.BIZOP_TEMPLATES +
            VerticalTemplatesService.HOME_IMPROVEMENT_TEMPLATES +
            VerticalTemplatesService.REFINANCE_TEMPLATES +
            VerticalTemplatesService.WIFI_TEMPLATES +
            VerticalTemplatesService.CBD_TEMPLATES +
            VerticalTemplatesService.BLOOD_SUGAR_TEMPLATES
        )

        for template_data in all_templates:
            existing = db.query(Template).filter(Template.id == template_data["id"]).first()
            if not existing:
                template = Template(
                    id=template_data["id"],
                    vertical=template_data["vertical"],
                    template_name=template_data["template_name"],
                    description=template_data["description"],
                    prompt_base=template_data["prompt_base"],
                    width=template_data["width"],
                    height=template_data["height"],
                    estimated_cost=template_data["estimated_cost"],
                    avg_ctr=template_data["avg_ctr"],
                    avg_conversion_rate=template_data["avg_conversion_rate"],
                    success_rate=template_data["success_rate"],
                    is_active=True,
                    is_featured=True,
                )
                db.add(template)
        db.commit()

    @staticmethod
    def add_custom_template(
        db: Session,
        vertical: str,
        template_name: str,
        prompt_base: str,
        description: str = None,
        width: int = 1200,
        height: int = 628,
        estimated_cost: float = 0.02,
    ) -> Template:
        """Add a custom template"""
        template = Template(
            id=f"{vertical}_{uuid.uuid4().hex[:8]}",
            vertical=vertical,
            template_name=template_name,
            description=description,
            prompt_base=prompt_base,
            width=width,
            height=height,
            estimated_cost=estimated_cost,
            is_active=True,
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return template
