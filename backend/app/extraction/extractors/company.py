"""Company name extraction from structured page metadata."""

from __future__ import annotations

import re
from typing import Optional

from app.core.enums import EvidenceType
from app.extraction.models import ExtractedClaim
from app.research.models import ResearchResult

_GENERIC_VALUES = {
    "home",
    "official site",
    "official website",
    "example",
    "company",
    "welcome",
}

_TITLE_SEPARATOR = re.compile(r"\s*[|\u2013\u2014\-]\s*")


def _name_rejected(name: str) -> bool:
    """Reject names that cannot identify a company (portal tokens, tiny names).

    ``name`` is a bare brand string (already stripped of punctuation). A
    single-token name shorter than four characters ("UK", "Six", "I'm") or made
    of site-structural portal tokens ("Conversations", "Funded") is not a
    company, and neither is a multi-token phrase that is entirely portal,
    geographic, or count words ("Angel Investors Network", "US Angel Investment
    Network", "Six Aussie"). Publisher/marketing brands ("Crunchbase",
    "Yahoo Finance", "Reddit") are rejected as candidate identities.
    """
    lowered = name.lower()
    if _is_publisher_brand(lowered):
        return True
    if lowered in _FINAL_BLOCKLIST:
        return True
    if re.search(r"\d", name):
        return True
    tokens = [token for token in lowered.split() if token]
    if len(tokens) == 1:
        # Reject very short/common/portal single tokens. Three-letter all-caps
        # acronyms ("IBM") stay, but short capitalized words ("Get", "Six",
        # "I'm") and two-letter marks ("UK", "US") are never a brand.
        if lowered in _SUPPRESS_LEAD_TOKENS:
            return True
        limit = 2 if name.isupper() else 3
        if len(name) <= limit:
            return True
    if len(tokens) >= 2 and all(token in _SUPPRESS_LEAD_TOKENS for token in tokens):
        return True
    return False


def _is_publisher_brand(name: str) -> bool:
    """True when a candidate identity is a publisher/marketing brand.

    Publisher write-ups and portals declare their own brand as the page
    ``og:site_name``, which would otherwise create a junk candidate named after
    the outlet. Distinctive brand strings are matched as substrings of the
    folded name so compound site names ("Inc. Arabia English – en.incarabia.com")
    are also caught.
    """
    slug = re.sub(r"[^a-z0-9]", "", name or "")
    return any(marker in slug for marker in _PUBLISHER_BRAND_MARKERS)


def _clean_brand_title(part: str) -> Optional[str]:
    """Read a short brand-like phrase from a bare title segment.

    Accepts only capitalized, filler-free phrases of up to four tokens
    ("Acme Robotics"). Editorial, list, and how-to headlines ("What is ...?",
    "The Best ..., 10+ ...", "The ... for ...") yield no brand, so pages whose
    site only shows a marketing phrase are skipped instead of becoming junk
    candidates.
    """
    lead: list[str] = []
    for token in part.split():
        norm = token.strip(" .,;:!?'\u2019\"()[]").strip()
        if not norm:
            break
        if not norm[0].isupper():
            break
        if norm.lower() in _GENERIC_LEAD_WORDS:
            break
        if len(lead) >= 4:
            break
        lead.append(norm)
    if not lead:
        return None
    name = " ".join(lead)
    if name.lower() in _GENERIC_VALUES:
        return None
    if _name_rejected(name):
        return None
    if any(ch in name for ch in "|:!?%\u2014\u2013"):
        return None
    return name


def _brand_name_from_title(text: str) -> Optional[str]:
    for part in _TITLE_SEPARATOR.split(text):
        candidate = _clean_brand_title(part)
        if candidate is not None:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Funding-announcement headlines
# ---------------------------------------------------------------------------
# A funding announcement headline ("Tower Raises €5.5 Million to Build ...")
# names the company at the start of the title. The company is read verbatim
# from the headline so publisher pages (whose ``og:site_name`` is the outlet,
# not the startup) no longer become the candidate. When a headline clearly
# announces funding but a clean company lead cannot be read, we skip the page
# instead of falling back to the publisher's site name.

# Headline must contain BOTH a raising/announcement verb AND a money/round
# signal before headline-driven name extraction applies.
_FUNDING_HEADLINE_VERB = re.compile(
    r"\b(?:raised|raises|raising|secures?|secured|closes?|closed|lands?|"
    r"announces?|announced|receives?|received|obtained|snags?|banks?|attracts?|"
    r"nabs?)\b",
    re.I,
)
_FUNDING_HEADLINE_SIGNAL = re.compile(
    r"\b(?:funding|round|seed|series(?:\s+[a-z])?|investment|financing|"
    r"million|billion)\b|(?:\$|€|£|USD|EUR|GBP)\s*\d",
    re.I,
)

# Stop tokens when reading the leading company phrase. Non-capitalized words,
# separators ("|", dashes), and these capitalized-but-generic words all cut the
# lead short.
#
# A small subset of headlined opening words ("SaaS", "Startup", "Platform",
# "The") are instead SKIPPED so a funding headline that opens with a category
# word still yields its true subject ("SaaS Startup Apptile Raises ..." ->
# "Apptile"). Only leading openers are skipped, at most three, and only while a
# brand token follows — a headline that is nothing but category words still
# yields no identity and the page is skipped, never guessed.
_SKIPPABLE_LEAD_WORDS = frozenset(
    "a an the saas software startup startups company companies firm scaleup "
    "unicorn platform solutions cloud app marketplace fintech".split()
)

_GENERIC_LEAD_WORDS = frozenset(
    "home welcome contact about blog news login help portfolio team careers "
    "list top best meet the a an of for and with in on at how what why "
    "startup startups company companies firm scaleup unicorn saas software "
    "platform solutions group fund capital ventures media labs shop store app "
    "web portal raised raises raising secure secures secured closed closes "
    "announced announces receive received obtains that this these its their "
    "from via based investor investors subscribe find compare government "
    "schemes grants grant guide apply services business funding funded "
    "entrepreneur".split()
)

# Words that disqualify a completed lead phrase (they identify a non-company
# heading rather than a company name). A brand's own word can legally appear
# inside a longer name ("DataPlatform"), so these tokens only reject when they
# are the ENTIRE candidate name; the funding-headline check uses them the same
# way.
_FINAL_BLOCKLIST = frozenset(
    "startup startups company companies firm scaleup unicorn list top best "
    "meet the a an saas fintech fund funds new about why how".split()
)

# Site-structural words that never form a company name on their own — and whose
# presence in a mostly-generic title means the page is a portal/landing page,
# not a company homepage ("Investor", "Find", "Compare", "Subscribe").
_PORTAL_BLOCK_TOKENS = frozenset(
    "investor investors angel angels network networks subscribe find compare "
    "government schemes grant grants funding funded entrepreneur apply services "
    "business portal magazine database directory conversations opinions events "
    "newsletter newsletters columns briefings announcements articles videos "
    "podcasts interviews press login sign up redirect redirection registration "
    "account profile settings documentation docs blog courses course academy "
    "conference summit submit welcome home upcoming coming soon start started "
    "news updates latest newsroom product products pricing features integrations "
    "logistical strategic partnerships partners partner".split()
)

# Count/ordinal words that open listicle headlines ("Six Aussie startups ...",
# "Ten UK scaleups ...") and are never a brand's leading word.
_CARDINAL_WORDS = frozenset(
    "one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty "
    "fifty sixty seventy eighty ninety hundred several few".split()
)

_GEO_PREFIXES = frozenset(
    "uk u.k. u.s. usa europe european eu africa african india indian german "
    "french british britain england english scottish welsh irish swedish "
    "denmark danish norway norwegian finland finnish netherlands dutch belgium "
    "belgian swiss sweden spain spanish portugal portuguese italy italian "
    "poland polish austrian ukraine ukrainian russia russian turkey turkish "
    "greece greek czech czechia hungary hungarian romania romanian bulgaria "
    "bulgarian croatia croatian serbia serbian israel israeli middleeast "
    "emirates uae egypt egyptian nigeria nigerian kenya kenyan southafrica "
    "saudi saudiarabia qatar qatari jordanian lebanon lebanese syria morocco "
    "moroccan tunisia algeria ethiopia ghana ghanian tanzania zimbabwe "
    "pakistan pakistani bangladesh bangladeshi srilanka srilankan nepal "
    "nepalese bhutan myanmar thailand thai malaysia malaysian indonesia "
    "indonesian philippines philippine filipino vietnam vietnamese cambodia "
    "cambodian laos laotian singapore japan japanese china chinese hongkong "
    "taiwan taiwanese korea korean australia australian aussie newzealand "
    "zealand nz canada canadian mexico mexican brazil brazilian argentina "
    "argentine argentinian chile chilean colombia colombian venezuela peru "
    "peruvian uruguay panama costa rica cuba cuban dominican "
    "berlin london paris madrid barcelona rome milan amsterdam brussels "
    "munich frankfurt hamburg zurich geneva vienna prague warsaw krakow "
    "stockholm oslo copenhagen helsinki dublin lisbon athens budapest "
    "bucharest sofia zagreb belgrade istanbul moscow kyiv "
    "newyork newyorkcity nyc sanfrancisco sf losangeles la seattle portland "
    "austin dallas houston chicago boston miami denver phoenix atlanta nashville "
    "toronto montreal vancouver mexicocity saopaulo buenosaires santiago "
    "lima bogota lagos nairobi cape town johannesburg cairo amman riyadh dubai "
    "doha telaviv jerusalem accra addis adissydney melbourne brisbane perth "
    "auckland wellington mumbai delhi bangalore hyderabad chennai pune "
    "kolkata ahmedabad jaipur newdelhi bengaluru gurugram noida "
    "singaporecity tokyo osaka kyoto seoul busan hongkong beijing shanghai "
    "shenzhen taipei bangkok jakarta manila hanoi hochiminhmumbai".split()
)

# Tokens that, together, can only spell a portal heading or listicle fragment
# ("Angel Investors Network", "US Angel Investment Network", "Six Aussie …").
_SUPPRESS_LEAD_TOKENS = _PORTAL_BLOCK_TOKENS | _GEO_PREFIXES | _CARDINAL_WORDS

# Distinctive publisher/marketing brand strings never accepted as a candidate
# identity. Substring matching against the folded name catches compound site
# names. Chosen to be specific enough not to collide with plausible startups.
_PUBLISHER_BRAND_MARKERS = frozenset(
    "crunchbase reddit redditinc yahoo yahoofinance yourstory vestbee kaggle "
    "msn siliconangle techcrunch thenextweb businessinsider marketwatch wsj "
    "reuters bloomberg forbes fortune cnbc theverge venturebeat techloy "
    "beststartup incarabia economictimes seedhits valueaddvc presswire "
    "globenewswire prnewswire businesswire accesswire media mohawk paypal "
    "linkedin wikipedia quora medium substack blueprint".split()
)


def _has_funding_headline_structure(text: str) -> bool:
    return bool(_FUNDING_HEADLINE_SIGNAL.search(text) and _FUNDING_HEADLINE_VERB.search(text))


def _company_from_funding_headline(text: str) -> Optional[str]:
    tokens = text.split()
    lead: list[str] = []
    skipped = 0
    for token in tokens:
        if any(ch in token for ch in "|\u2013\u2014\u201c\u201d"):
            break
        norm = token.strip(" .,;:!?'\u2019\"").strip()
        if not norm:
            break
        low = norm.lower()
        if low in _SKIPPABLE_LEAD_WORDS and skipped < 3:
            skipped += 1
            continue
        if not norm[0].isupper():
            break
        if low in _GENERIC_LEAD_WORDS:
            break
        if len(lead) >= 4:
            break
        lead.append(norm)
    while lead and (
        re.match(r"^[A-Za-z]+[-–]?based$", lead[0], re.I) is not None
        or lead[0].lower() in _GEO_PREFIXES
        or lead[0].lower() in _CARDINAL_WORDS
    ):
        lead.pop(0)
    if not lead:
        return None
    name = " ".join(lead)
    if _name_rejected(name):
        return None
    if name.isupper() and len(name) <= 3:
        return None
    return name


def extract_company(
    research: ResearchResult, source_title: str | None = None
) -> list[ExtractedClaim]:
    """Best-guess company name.

    Order of preference:
      1. A funding-announcement headline ("Tower Raises €5.5M ...") names the
         company at the start of the title; it is used verbatim so publisher
         pages are no longer mistaken for the startup. An announcement
         headline whose company lead cannot be read cleanly yields NO claim.
      2. Open Graph ``site_name`` (a company's own site).
      3. Page title, then Open Graph title.

    Returns an empty list when no reliable identity can be found, so the
    service can skip persistence instead of guessing.
    """
    claims: list[ExtractedClaim] = []
    source_url = research.final_url or research.source_url

    for headline in (
        (research.metadata.title or "").strip(),
        (research.metadata.og_title or "").strip(),
    ):
        if not headline or not _has_funding_headline_structure(headline):
            continue
        name = _company_from_funding_headline(headline)
        if name is None:
            # A funding announcement we cannot read a company from must never
            # fall back to the publisher's site name.
            return []
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.COMPANY_NAME,
                field="company_name",
                value=name,
                normalized_value=name,
                context=f"funding announcement headline: {headline}",
                source_url=source_url,
                source_title=source_title,
                confidence=0.7,
            )
        )
        return claims

    og_site = (research.metadata.og_site_name or "").strip()
    if og_site and og_site.lower() not in _GENERIC_VALUES and not _name_rejected(og_site):
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.COMPANY_NAME,
                field="company_name",
                value=og_site,
                normalized_value=og_site,
                context="Open Graph site_name",
                source_url=source_url,
                source_title=source_title,
                confidence=0.8,
            )
        )
        return claims

    title = (research.metadata.title or "").strip()
    cleaned = _brand_name_from_title(title) if title else None
    if cleaned:
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.COMPANY_NAME,
                field="company_name",
                value=cleaned,
                normalized_value=cleaned,
                context=f"page title: {title}",
                source_url=source_url,
                source_title=source_title,
                confidence=0.6,
            )
        )
        return claims

    og_title = (research.metadata.og_title or "").strip()
    cleaned = _brand_name_from_title(og_title) if og_title else None
    if cleaned:
        claims.append(
            ExtractedClaim(
                claim_type=EvidenceType.COMPANY_NAME,
                field="company_name",
                value=cleaned,
                normalized_value=cleaned,
                context=f"Open Graph title: {og_title}",
                source_url=source_url,
                source_title=source_title,
                confidence=0.5,
            )
        )
        return claims

    return []