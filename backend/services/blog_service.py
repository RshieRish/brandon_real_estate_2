"""
Blog Service for Sold With Sweeney & Co.

Two-stage Gemini pipeline:
  Stage A: Research  — gemini-3-flash-preview  (fast, broad context)
  Stage B: Writing   — gemini-3-pro-preview    (high-quality long-form)
  Stage C: Image     — gemini-3-pro-image-preview via REST (editorial cover image)

Author: Fixed persona — Stephanie Mitchell, Real Estate Content Director
Topics: 5 rotating real estate content buckets (MA, NH, Brandon, REALTOR®, Buyers)
Storage: R2 (if configured) → public/ dir fallback → placeholder URL
"""

from __future__ import annotations

import base64
import os
import random
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import requests
from google import genai
from google.genai import types

from config import settings

# ---------------------------------------------------------------------------
# Gemini client (new google-genai SDK)
# ---------------------------------------------------------------------------
_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

# ---------------------------------------------------------------------------
# Fixed author persona — never regenerated per-blog
# ---------------------------------------------------------------------------
SWEENEY_AUTHOR = {
    "name": "Stephanie Mitchell",
    "role": "Real Estate Content Director, Sold With Sweeney & Co.",
    "bio": (
        "Stephanie has spent over a decade covering the New England real estate market, "
        "with a focus on Northern Massachusetts and Southern New Hampshire. She works closely "
        "with Brandon Sweeney's team to deliver insightful, actionable content for buyers, "
        "sellers, and investors navigating one of the most competitive markets in the country."
    ),
    "image_url": "https://picsum.photos/seed/sweeney-stephanie/200/200",
}

# ---------------------------------------------------------------------------
# Content buckets — LRU rotation so topics don't repeat
# ---------------------------------------------------------------------------
CONTENT_BUCKETS = [
    "MA Real Estate",
    "NH Real Estate",
    "Brandon Sweeney",
    "REALTOR® Insights",
    "First-Time Buyers",
]

# Curated topic pools per bucket
TOPIC_POOL: Dict[str, List[str]] = {
    "MA Real Estate": [
        "2025 Northern Massachusetts Housing Market Forecast",
        "Best Towns in Northern MA for First-Time Buyers",
        "How to Win a Bidding War in the Merrimack Valley",
        "Dracut vs. Andover: Where Should You Buy in 2025?",
        "Why Lowell's Real Estate Market Is Turning Heads",
        "What the Fed Rate Changes Mean for MA Home Buyers",
        "Selling Your MA Home in a Buyer's Market: A Tactical Guide",
        "The Most Underrated Neighborhoods in Northern Massachusetts",
        "Massachusetts Property Taxes: What Buyers Need to Know",
        "How to Sell Your MA Home for Over Asking Price",
    ],
    "NH Real Estate": [
        "Why Southern New Hampshire Is the Hottest Market Right Now",
        "Salem NH Real Estate: What's Driving the Boom",
        "Nashua vs. Manchester: Where Should MA Buyers Look?",
        "No Income Tax, Great Schools: Why Families Are Moving to NH",
        "The Southern NH Town Every Investor Should Watch in 2025",
        "Comparing NH and MA Property Taxes: A Buyer's Guide",
        "How to Buy a Home in NH as a Massachusetts Resident",
        "Windham, Londonderry, Salem: NH's Golden Triangle for Families",
        "NH Housing Inventory Crisis: What It Means for Buyers",
        "Why More Boston Professionals Are Relocating to Southern NH",
    ],
    "Brandon Sweeney": [
        "A Day in the Life of a Top REALTOR® in Northern Massachusetts",
        "How Brandon Sweeney Became REALTOR® of the Year in 2025",
        "50+ Transactions and Counting: Brandon's Approach to Real Estate",
        "Why Brandon Sweeney Gives Back: Real Estate & Community Impact",
        "From First Deal to NEAR President: Brandon Sweeney's Journey",
        "How Brandon Sweeney Negotiates Above Asking Price Every Time",
        "What Brandon Sweeney's Clients Say About Working With Him",
        "Brandon's Morning Routine: How a Top Agent Starts the Day",
        "Why Brandon Sweeney Chose Keller Williams for His Business",
        "How Brandon Sweeney Balances Real Estate, Family, and Giving Back",
    ],
    "REALTOR® Insights": [
        "What Separates a Great REALTOR® from an Average One",
        "Red Flags When Interviewing a Real Estate Agent in MA or NH",
        "Why Your Agent's Negotiation Skills Are Worth More Than Their Commission",
        "How to Choose a REALTOR® in a Competitive Market",
        "The Hidden Costs of Using the Wrong Agent to Sell Your Home",
        "What Does 'Licensed Real Estate Agent' Actually Mean in Massachusetts?",
        "REALTOR® vs. Real Estate Agent: What's the Difference?",
        "How Real Estate Agents Are Paid — And Why It Matters to You",
        "The Questions Every Buyer Should Ask Their Agent Before Starting",
        "Why Local Expertise Is the Most Valuable Thing Your Agent Can Offer",
    ],
    "First-Time Buyers": [
        "First-Time Home Buyer Guide: Massachusetts vs. New Hampshire",
        "Down Payment Assistance Programs in Massachusetts 2025",
        "How to Buy Your First Home in 90 Days With Brandon Sweeney",
        "Pre-Approval vs. Pre-Qualification: What Every First-Timer Must Know",
        "The Complete Closing Cost Breakdown for MA and NH First-Time Buyers",
        "How Much House Can You Actually Afford in Northern MA or Southern NH?",
        "10 Mistakes First-Time Buyers Make (And How to Avoid Them)",
        "FHA vs. Conventional Loans: Which Is Right for You in 2025?",
        "The First-Time Buyer's Timeline: From Offer to Move-In",
        "What No One Tells First-Time Home Buyers About the Inspection",
    ],
}

# ---------------------------------------------------------------------------
# R2 / S3 storage (optional — falls back to public/ dir if not configured)
# ---------------------------------------------------------------------------
_s3_client = None
_R2_BUCKET = settings.R2_BUCKET_NAME or "sws"
_R2_PUBLIC_URL = settings.R2_PUBLIC_URL or ""

try:
    import boto3
    if settings.R2_ENDPOINT and settings.R2_ACCESS_KEY_ID and settings.R2_SECRET_ACCESS_KEY:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name=settings.R2_REGION or "auto",
        )
        print(f"[Blog] R2 storage configured — bucket: {_R2_BUCKET}")
    else:
        print("[Blog] R2 not configured — will save images to public/ dir.")
except ImportError:
    print("[Blog] boto3 not installed — image upload to R2 disabled.")



# ---------------------------------------------------------------------------
# Helper: pick a topic from the LRU-least-used bucket
# ---------------------------------------------------------------------------

def _get_topic_and_category(existing_categories: List[str]) -> tuple[str, str]:
    """Pick the bucket used least recently, then a random unused topic."""
    from collections import Counter
    counts = Counter(existing_categories)
    # Sort buckets by usage (ascending) so least-used comes first
    sorted_buckets = sorted(CONTENT_BUCKETS, key=lambda b: counts.get(b, 0))
    bucket = sorted_buckets[0]
    return random.choice(TOPIC_POOL[bucket]), bucket


# ---------------------------------------------------------------------------
# Helper: estimate reading time from word count
# ---------------------------------------------------------------------------

def _estimate_read_time(text: str) -> int:
    words = len(text.split())
    return max(1, round(words / 238))  # avg reading speed ~238 wpm


# ---------------------------------------------------------------------------
# Helper: extract first paragraph as excerpt
# ---------------------------------------------------------------------------

def _extract_excerpt(content: str, max_chars: int = 220) -> str:
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        # Skip H1, H2, empty lines
        if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
            clean = re.sub(r"[*_`\[\]]", "", stripped)
            return clean[:max_chars] + ("…" if len(clean) > max_chars else "")
    return ""


# ---------------------------------------------------------------------------
# Helper: save image bytes to Next.js public dir (fallback)
# ---------------------------------------------------------------------------

def _save_image_to_public(image_bytes: bytes, ext: str = "jpg") -> str:
    """Save image to Next.js frontend public/blog-images/ and return the URL path."""
    try:
        # Navigate up: backend/services/ → backend/ → project root → frontend/public/
        base = Path(__file__).parent.parent.parent  # project root
        pub_dir = base / "frontend" / "public" / "blog-images"
        pub_dir.mkdir(parents=True, exist_ok=True)
        filename = f"blog-{int(time.time())}-{random.randint(1000, 9999)}.{ext}"
        (pub_dir / filename).write_bytes(image_bytes)
        return f"/blog-images/{filename}"
    except Exception as exc:
        print(f"[Blog] Failed to save image to public dir: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Helper: upload image bytes to R2 or fall back to public dir
# ---------------------------------------------------------------------------

def _upload_image(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    ext = "png" if "png" in mime else "jpg"
    filename = f"blog-images/blog-{int(time.time())}-{random.randint(1000, 9999)}.{ext}"

    if _s3_client and _R2_PUBLIC_URL:
        try:
            _s3_client.upload_fileobj(
                BytesIO(image_bytes),
                _R2_BUCKET,
                filename,
                ExtraArgs={"ContentType": mime},
            )
            url = f"{_R2_PUBLIC_URL.rstrip('/')}/{filename}"
            print(f"[Blog] Image uploaded to R2: {url}")
            return url
        except Exception as exc:
            print(f"[Blog] R2 upload failed: {exc} — falling back to public dir.")

    url = _save_image_to_public(image_bytes, ext)
    if url:
        print(f"[Blog] Image saved to public dir: {url}")
        return url

    print("[Blog] All image storage methods failed — using placeholder.")
    return "https://placehold.co/1200x630/0a0a0a/eac469?text=Sold+With+Sweeney"


# ===========================================================================
# BlogService
# ===========================================================================

class BlogService:

    # -----------------------------------------------------------------------
    # Stage A: Research (gemini-3-flash-preview — fast, broad)
    # -----------------------------------------------------------------------
    @staticmethod
    async def _stage_a_research(topic: str, category: str) -> str:
        prompt = f"""You are a real estate market research expert supporting Brandon Sweeney, a top-producing REALTOR® in Northern Massachusetts and Southern New Hampshire. Brandon is the 2025 NEAR President and REALTOR® of the Year, licensed since 2017, with Keller Williams.

Topic to research: "{topic}"
Content category: {category}

Conduct thorough research for this blog post. Output structured research notes with:

## Search Intent
What are readers searching for? What questions does this post answer?

## Core Thesis
The single most compelling angle or argument for this post.

## Market Signals
3–5 current market facts, trends, or data points specific to MA and/or NH real estate.

## Brandon Sweeney Angle
How can Brandon Sweeney's expertise, story, or client results be woven in naturally?

## Local Specifics
Specific towns, neighborhoods, zip codes, or local nuances that add authenticity (Dracut, Andover, Salem NH, Nashua, Manchester, Windham, Londonderry, etc.)

## Data & Statistics
Concrete numbers: prices, inventory levels, days on market, appreciation rates, tax rates, program limits, etc.

## External Sources
2–4 authoritative sources to cite (NAR, Massachusetts Association of REALTORS®, NH Housing Finance Authority, zillow.com, realtor.com, census.gov, mass.gov, nh.gov, etc.)

## Research Notes for Intro
A vivid hook sentence or scenario that will open the article powerfully.

Do NOT write the blog post yet. Only output research notes."""

        response = await _gemini_client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        return response.text

    # -----------------------------------------------------------------------
    # Stage B: Writing (gemini-3-pro-preview — high quality, long form)
    # -----------------------------------------------------------------------
    @staticmethod
    async def _stage_b_writing(research_notes: str, topic: str, category: str) -> str:
        service_map = {
            "MA Real Estate": "/buy",
            "NH Real Estate": "/buy",
            "Brandon Sweeney": "/about",
            "REALTOR® Insights": "/about",
            "First-Time Buyers": "/buy",
        }
        cta_page = service_map.get(category, "/about")

        prompt = f"""You are Stephanie Mitchell, Real Estate Content Director for Sold With Sweeney & Co. You write authoritative, warm, locally-specific blog posts about real estate in Massachusetts and New Hampshire. You work directly with Brandon Sweeney's team. Your writing is clear, confident, and guides readers toward taking action — booking a consultation with Brandon.

CRITICAL BRAND RULES:
- REALTOR® must ALWAYS be written with the ® mark
- Brandon is a "licensed real estate agent" (not "licensed REALTOR®" — REALTOR® is a membership mark)
- Refer to Brandon as a REALTOR® only when discussing his membership, awards, or the National Association of REALTORS®
- Brandon serves "Northern Massachusetts and Southern New Hampshire" (never "Merrimack Valley")
- No emojis anywhere in the post
- Company: Sold With Sweeney & Co., powered by Keller Williams Realty Success

Topic: "{topic}"
Category: {category}

Research Notes:
{research_notes}

Write a comprehensive, high-ranking SEO blog post. This must be 1,200–1,800 words and read like a premium editorial guide.

## STRICT REQUIREMENTS

### Structure
1. **# Title** — SEO-optimized, specific, compelling (this is your H1)
2. **Introduction** — Open with the hook from the research. Address the reader directly.
3. **## [Section 1]** — Core educational content
4. **## [Section 2]** — Local specifics (towns, data, market reality)
5. **## [Section 3]** — Practical guidance or comparison
6. **## [Section 4]** — Brandon Sweeney's expertise or perspective
7. **## [Section 5]** — What to do next / how to take action
8. **## Conclusion** — Strong recap + CTA to book with Brandon

### Formatting (renders via react-markdown)
- Use `# ` for title (H1) — exactly ONE H1
- Use `## ` for main sections — at least 5 sections
- Use `### ` for subsections where helpful
- **Bold** key terms and important numbers
- Use bullet and numbered lists liberally for scannability
- Use `> ` blockquotes for expert tips
- ALL tables MUST use pipe syntax with header separator row

### Links
- Include at least 2 internal links: [Buy a Home with Brandon](https://soldwithsweeney.com{cta_page}) and [About Brandon](https://soldwithsweeney.com/about)
- Include at least 2–3 external authoritative links (NAR, MAR, NH Housing, mass.gov, nh.gov, etc.)

### Tone
- Write as Stephanie — warm, expert, locally knowledgeable
- Address reader as "you" / "your home" / "your search"
- Mention Brandon naturally (3rd person) — his expertise, results, approach
- End with a clear, warm CTA to book a strategy call with Brandon

### Do NOT
- Include an author byline (handled separately)
- Use placeholder URLs
- Write fewer than 1,100 words
- Use H1 (#) anywhere except the title"""

        response = await _gemini_client.aio.models.generate_content(
            model="gemini-3-pro-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=6000,
                temperature=0.7,
            ),
        )
        return response.text

    # -----------------------------------------------------------------------
    # Stage C: Image generation (gemini-3-pro-image-preview via REST)
    # -----------------------------------------------------------------------
    @staticmethod
    def generate_blog_image(title: str) -> str:
        """Generate a photorealistic editorial cover image for the blog post."""
        image_prompt = (
            f"Photorealistic editorial header image (16:9, 2K resolution) for a New England real estate blog post titled: '{title}'. "
            "Cinematic composition. Warm golden hour light over a suburban New England neighborhood — colonial homes, maple trees, autumn leaves OR fresh spring greenery. "
            "Premium aesthetic. No text overlays. No people in frame. Sony A1 style, 85mm, f/1.8, crisp details, shallow depth of field. "
            "Mood: aspirational, warm, professional. Dark vignette edges. Color palette: warm golds, deep greens, cream facades, slate roofs."
        )

        gemini_key = settings.GEMINI_API_KEY
        if not gemini_key:
            print("[Blog] GEMINI_API_KEY not set — using placeholder image.")
            return "https://placehold.co/1200x630/0a0a0a/eac469?text=Sold+With+Sweeney"

        try:
            print(f"[Blog] Generating image for: {title[:60]}...")
            endpoint = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-3-pro-image-preview:generateContent?key={gemini_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": image_prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
            }
            resp = requests.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                for part in data["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        mime = part["inlineData"].get("mimeType", "image/jpeg")
                        image_bytes = base64.b64decode(part["inlineData"]["data"])
                        return _upload_image(image_bytes, mime)
                print("[Blog] Gemini returned 200 but no image data.")
            else:
                print(f"[Blog] Gemini image error {resp.status_code}: {resp.text[:300]}")
        except Exception as exc:
            print(f"[Blog] Image generation failed: {exc}")

        return "https://placehold.co/1200x630/0a0a0a/eac469?text=Sold+With+Sweeney"

    # -----------------------------------------------------------------------
    # Full pipeline: generate a complete blog post
    # -----------------------------------------------------------------------
    @staticmethod
    async def generate_blog_content(
        topic: Optional[str],
        category: Optional[str],
        existing_categories: Optional[List[str]] = None,
    ) -> Dict:
        """Run the two-stage Gemini pipeline and return a dict with all blog fields."""
        if not category or not topic:
            resolved_topic, resolved_category = _get_topic_and_category(existing_categories or [])
            topic = topic or resolved_topic
            category = category or resolved_category

        print(f"[Blog] Generating — Category: {category} | Topic: {topic}")

        # Stage A + B (research then write)
        research = await BlogService._stage_a_research(topic, category)
        content = await BlogService._stage_b_writing(research, topic, category)

        # Extract title from H1
        title = topic  # fallback
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                title = re.sub(r"[*_`]", "", title)
                break

        # Build slug
        slug = re.sub(r"[^a-z0-9\s-]", "", title.lower()).strip()
        slug = re.sub(r"\s+", "-", slug)[:100]

        excerpt = _extract_excerpt(content)
        read_time = _estimate_read_time(content)

        return {
            "title": title,
            "slug": slug,
            "content": content,
            "excerpt": excerpt,
            "category": category,
            "read_time_mins": read_time,
            **SWEENEY_AUTHOR,  # name, role, bio, image_url → mapped below
        }

    # -----------------------------------------------------------------------
    # DB helpers (raw psycopg2 — matches existing Brandon backend pattern)
    # -----------------------------------------------------------------------
    @staticmethod
    def _get_conn():
        import psycopg2
        # Strip asyncpg+postgresql prefix to get a sync URL
        db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        return psycopg2.connect(db_url)

    @staticmethod
    def _get_existing_categories() -> List[str]:
        conn = BlogService._get_conn()
        try:
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor()
            cur.execute("SELECT category FROM blogs WHERE category IS NOT NULL ORDER BY created_at DESC LIMIT 30")
            return [r[0] for r in cur.fetchall()]
        except Exception as exc:
            print(f"[Blog] Error fetching categories: {exc}")
            return []
        finally:
            conn.close()

    @staticmethod
    async def create_auto_blog() -> Dict:
        """Auto-pilot: pick topic, generate full post, save to DB as published."""
        existing = BlogService._get_existing_categories()
        blog_data = await BlogService.generate_blog_content(None, None, existing)
        image_url = BlogService.generate_blog_image(blog_data["title"])
        return BlogService._save_blog(blog_data, image_url, is_posted=True)

    @staticmethod
    async def create_draft_blog(topic: str, category: str) -> Dict:
        """Semi-auto: admin picks topic → Gemini generates → saved as draft."""
        blog_data = await BlogService.generate_blog_content(topic, category, [])
        image_url = BlogService.generate_blog_image(blog_data["title"])
        return BlogService._save_blog(blog_data, image_url, is_posted=False)

    @staticmethod
    def create_manual_blog(
        title: str,
        content: str,
        category: str,
        is_posted: bool,
        image_file=None,
    ) -> Dict:
        """Manual mode: admin provides all content."""
        image_url = None
        if image_file:
            if hasattr(image_file, "file"):
                raw = image_file.file.read()
                mime = getattr(image_file, "content_type", "image/jpeg")
            else:
                raw = image_file
                mime = "image/jpeg"
            image_url = _upload_image(raw, mime)

        slug = re.sub(r"[^a-z0-9\s-]", "", title.lower()).strip()
        slug = re.sub(r"\s+", "-", slug)[:100]
        excerpt = _extract_excerpt(content)
        read_time = _estimate_read_time(content)

        blog_data = {
            "title": title,
            "slug": slug,
            "content": content,
            "excerpt": excerpt,
            "category": category,
            "read_time_mins": read_time,
            "name": SWEENEY_AUTHOR["name"],
            "role": SWEENEY_AUTHOR["role"],
            "bio": SWEENEY_AUTHOR["bio"],
            "image_url_author": SWEENEY_AUTHOR["image_url"],
        }
        return BlogService._save_blog(blog_data, image_url, is_posted=is_posted)

    @staticmethod
    def _save_blog(blog_data: Dict, image_url: Optional[str], is_posted: bool) -> Dict:
        conn = BlogService._get_conn()
        try:
            cur = conn.cursor()
            # Resolve author fields (either from SWEENEY_AUTHOR spread or explicit keys)
            author_name = blog_data.get("name") or SWEENEY_AUTHOR["name"]
            author_role = blog_data.get("role") or SWEENEY_AUTHOR["role"]
            author_bio = blog_data.get("bio") or SWEENEY_AUTHOR["bio"]
            author_img = blog_data.get("image_url") or blog_data.get("image_url_author") or SWEENEY_AUTHOR["image_url"]

            cur.execute(
                """
                INSERT INTO blogs (
                    title, slug, content, excerpt, image_url, category,
                    author, author_role, author_bio, author_image_url,
                    is_posted, read_time_mins, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (slug) DO UPDATE SET slug = blogs.slug || '-' || extract(epoch from now())::int
                RETURNING id
                """,
                (
                    blog_data["title"],
                    blog_data["slug"],
                    blog_data["content"],
                    blog_data.get("excerpt"),
                    image_url,
                    blog_data.get("category"),
                    author_name,
                    author_role,
                    author_bio,
                    author_img,
                    is_posted,
                    blog_data.get("read_time_mins"),
                ),
            )
            blog_id = str(cur.fetchone()[0])
            conn.commit()
            print(f"[Blog] Saved blog id={blog_id} | posted={is_posted}")
            return {**blog_data, "id": blog_id, "image_url": image_url, "is_posted": is_posted}
        except Exception as exc:
            conn.rollback()
            print(f"[Blog] DB save failed: {exc}")
            raise
        finally:
            conn.close()
