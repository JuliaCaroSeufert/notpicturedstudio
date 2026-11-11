"""Brief screening before anything is generated."""

from __future__ import annotations

import re

from nps.core.models import Brief, CheckResult, ProductCategory

EXCLUDED_CATEGORIES_V1 = frozenset(
    {
        ProductCategory.DIAPERS,
        ProductCategory.BATH,
        ProductCategory.SWIMWEAR,
        ProductCategory.UNDERWEAR,
    }
)

# Deliberately broad: a false rejection costs a rephrased brief, a miss costs far
# more. Covers German and English terms for diaper, bath, swim and undress
# contexts. Stems in the first group match inside compounds ("Schwimmwindel",
# "Babybadewanne"); the second group needs a word start to avoid hits such as
# "entwickeln" or "carpool". This is a first line only; it does not replace the
# checks on the generated image.
_EXCLUDED_TERMS = re.compile(
    r"(\w*(?:windel|diaper|bade|wanne|bath|dusch|shower|schwimm|swim|plansch|"
    r"unterw[aä]sche|unterhose|underwear|nackt|naked|unbekleidet|unclothed)\w*"
    r"|\b(?:nappy|nappies|wickel\w*|pool\w*|strand\w*|beach\w*|nude\w*|undress\w*|"
    r"ausgezogen\w*|oberk[oö]rperfrei|shirtless|topless|im bad)\b)",
    re.IGNORECASE,
)


# v1 covers ages 2 to 10. Infants and ages 11 to 17 follow in v2.
MIN_AGE_V1, MAX_AGE_V1 = 2, 10


def screen_brief(brief: Brief) -> CheckResult:
    """Reject briefs in categories, contexts or age ranges that are excluded in v1."""
    reasons: list[str] = []
    if not MIN_AGE_V1 <= brief.child.age_years <= MAX_AGE_V1:
        reasons.append(
            f"age {brief.child.age_years} is outside the v1 range {MIN_AGE_V1} to {MAX_AGE_V1}"
        )
    if brief.product_category in EXCLUDED_CATEGORIES_V1:
        reasons.append(f"product category '{brief.product_category.value}' is excluded in v1")

    for field, text in (
        ("product_name", brief.product_name),
        ("scene", brief.scene),
        ("child.description", brief.child.description),
    ):
        terms = sorted({match.group(0).lower() for match in _EXCLUDED_TERMS.finditer(text)})
        if terms:
            reasons.append(f"{field} contains excluded terms: {', '.join(terms)}")

    return CheckResult(check="brief_screening", passed=not reasons, details={"reasons": reasons})
