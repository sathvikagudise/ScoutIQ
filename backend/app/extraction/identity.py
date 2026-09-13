"""Conservative candidate identity matching.

Two pages describe the SAME candidate only when their normalized websites or
normalized company names are identical. Anything fuzzier (fuzzy matching,
sound-alikes, domain guessing) risks merging distinct companies, so it is
deliberately out of scope.
"""

from __future__ import annotations

from typing import Optional

from app.extraction.support import normalize_company_name, normalize_website
from app.models.company import CompanyCandidate


def find_existing_candidate(
    candidates: list[CompanyCandidate],
    *,
    company_name: Optional[str],
    website: Optional[str],
) -> Optional[CompanyCandidate]:
    """Return the candidate already representing this identity, or None."""
    if website:
        website_key = normalize_website(website)
        for candidate in candidates:
            if candidate.official_website and normalize_website(candidate.official_website) == website_key:
                return candidate

    if company_name:
        name_key = normalize_company_name(company_name)
        for candidate in candidates:
            if candidate.company_name and normalize_company_name(candidate.company_name) == name_key:
                return candidate

    return None