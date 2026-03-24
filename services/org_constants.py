# services/org_constants.py
"""
Org ID boundaries — single source of truth.

College orgs: 31-338 (original) + 341-342 (expansion).
Orgs 339 (INTAM) and 340 (USHS) sit in the gap and are NOT college.
"""

MLB_ORG_MIN = 1
MLB_ORG_MAX = 30

COLLEGE_ORG_MIN = 31
COLLEGE_ORG_MAX = 342
INTAM_ORG_ID = 339
USHS_ORG_ID = 340
IFA_TARGET_LEVEL = 4

# Non-college orgs inside the college min/max range
_NON_COLLEGE_IN_RANGE = frozenset({INTAM_ORG_ID, USHS_ORG_ID})


def is_college_org(org_id: int) -> bool:
    """True if org_id belongs to a college program."""
    return (COLLEGE_ORG_MIN <= org_id <= COLLEGE_ORG_MAX
            and org_id not in _NON_COLLEGE_IN_RANGE)
