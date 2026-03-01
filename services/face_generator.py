# services/face_generator.py
"""
Deterministic player face generator for facesjs v4.3.3.

Generates FaceDataResponse dicts from player IDs using a seeded RNG.
Same player_id + same config always produces the same face.

No DB access for face generation itself — pure computation.
The load_face_config() helper reads admin-adjustable probabilities
from the face_gen_config table.
"""

import json
import logging
import random
from typing import Any, Dict, List, Optional

from sqlalchemy import Table, MetaData, select, text

logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# facesjs v4.3.3 SVG asset IDs (male-appropriate, from src/svgs/ on GitHub)
# ---------------------------------------------------------------------------

HEAD_IDS = [f"head{i}" for i in range(1, 19)]  # head1–head18

BODY_IDS = ["body", "body2", "body3", "body4", "body5"]

EAR_IDS = ["ear1", "ear2", "ear3"]

EYE_IDS = [f"eye{i}" for i in range(1, 20)]  # eye1–eye19

EYEBROW_IDS = [f"eyebrow{i}" for i in range(1, 21)]  # eyebrow1–eyebrow20

EYELINE_IDS = ["line1", "line2", "line3", "line4", "line5", "line6"]

NOSE_IDS = [
    *[f"nose{i}" for i in range(1, 15)],  # nose1–nose14
    "honker", "pinocchio", "small",
]

MOUTH_IDS = [
    "angry", "closed", "mouth",
    *[f"mouth{i}" for i in range(2, 9)],  # mouth2–mouth8
    "side", "smile-closed", "smile",
    "smile2", "smile3", "smile4", "straight",
]

HAIR_IDS = [
    "afro", "afro2", "bald", "blowoutFade", "cornrows",
    "crop-fade", "crop-fade2", "crop",
    "curly", "curly2", "curly3", "curlyFade1", "curlyFade2",
    "dreads", "emo", "faux-hawk", "fauxhawk-fade",
    "hair", "high", "juice", "longHair",
    "messy-short", "messy", "middle-part", "parted",
    "shaggy1", "shaggy2",
    "short-bald", "short-fade", "short", "short2", "short3",
    "shortBangs",
    "spike", "spike2", "spike3", "spike4",
    "tall-fade",
]

HAIRBG_IDS = ["longHair", "shaggy"]  # non-"none" options

FACIALHAIR_IDS = [
    "beard-point",
    *[f"beard{i}" for i in range(1, 7)],  # beard1–beard6
    "chin-strap", "chin-strapStache",
    *[f"fullgoatee{'' if i == 1 else i}" for i in range(1, 7)],
    "mustache", "mustache-thin",
    "goatee",
    "sideburns1", "sideburns2", "sideburns3",
    "soul", "soul-stache",
]

JERSEY_IDS = ["baseball", "baseball2", "baseball3", "baseball4"]

GLASSES_IDS = [
    "glasses1-primary", "glasses1-secondary",
    "glasses2-black", "glasses2-primary", "glasses2-secondary",
    "facemask",
]

ACCESSORIES_IDS = [
    "eye-black", "hat", "hat2", "hat3",
    "headband-high", "headband",
]

MISCLINE_IDS = [
    "blush", "chin1", "chin2",
    *[f"forehead{i}" for i in range(1, 6)],  # forehead1–forehead5
    "freckles1", "freckles2",
]

SMILELINE_IDS = ["line1", "line2", "line3", "line4"]

# ---------------------------------------------------------------------------
# Color palettes (merged across facesjs race categories)
# ---------------------------------------------------------------------------

SKIN_COLORS = [
    "#f2d6cb", "#ddb7a0", "#ce967d", "#c89886",
    "#f5dbad", "#ebcd96", "#d5a67b", "#c48e6c",
    "#bb876f", "#aa7b64", "#a67358", "#96674d",
    "#8d5638", "#7e4e33", "#6b4027", "#5c3625",
]

HAIR_COLORS = [
    "#090806", "#2c222b", "#3b302a", "#4e433f",
    "#504444", "#6a4e42", "#a55728", "#b55239",
    "#8d4a43", "#91553d", "#c9c49a", "#e3cc88",
    "#d6c4c2", "#cabfb1", "#b1ada0", "#888175",
]

# ---------------------------------------------------------------------------
# Default probabilities for optional features (facesjs male defaults)
# ---------------------------------------------------------------------------

DEFAULT_FREQUENCIES: Dict[str, float] = {
    "glasses_pct":     0.10,
    "accessories_pct": 0.20,
    "facialHair_pct":  0.50,
    "eyeLine_pct":     0.75,
    "smileLine_pct":   0.75,
    "miscLine_pct":    0.50,
    "hairBg_pct":      0.10,
}

# ---------------------------------------------------------------------------
# Numeric ranges (facesjs generate.ts numberRanges, male values)
# ---------------------------------------------------------------------------

_NUMERIC_RANGES = {
    "BodySize":      (0.95, 1.05),
    "FaceSize":      (0.0, 1.0),
    "EarSize":       (0.5, 1.5),
    "NoseSize":      (0.5, 1.25),
    "SmileLineSize": (0.25, 2.25),
    "EyeAngle":      (-10.0, 15.0),
    "EyeBrowAngle":  (-15.0, 20.0),
}

# head.shave range for males
_SHAVE_RANGE = (0.0, 0.2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_face(player_id: int, config: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Generate a deterministic FaceDataResponse for one player.

    Args:
        player_id: Unique player identifier (used as RNG seed).
        config: Optional probability overrides from face_gen_config table.
                Falls back to DEFAULT_FREQUENCIES when None.

    Returns:
        Flat dict with PascalCase keys matching the frontend FaceDataResponse.
    """
    rng = random.Random(player_id)
    freq = {**DEFAULT_FREQUENCIES, **(config or {})}

    def _pct(key: str) -> float:
        return float(freq.get(key, DEFAULT_FREQUENCIES.get(key, 0.5)))

    def _optional(ids: list, pct_key: str) -> str:
        """Pick from ids with probability pct_key, otherwise 'none'."""
        if rng.random() < _pct(pct_key):
            return rng.choice(ids)
        return "none"

    def _ranged(key: str) -> float:
        lo, hi = _NUMERIC_RANGES[key]
        return round(rng.uniform(lo, hi), 2)

    return {
        # Structure (always present)
        "Head":     rng.choice(HEAD_IDS),
        "Body":     rng.choice(BODY_IDS),
        "Ear":      rng.choice(EAR_IDS),
        "Eye":      rng.choice(EYE_IDS),
        "Eyebrow":  rng.choice(EYEBROW_IDS),
        "Nose":     rng.choice(NOSE_IDS),
        "Mouth":    rng.choice(MOUTH_IDS),
        "Hair":     rng.choice(HAIR_IDS),
        "Jersey":   rng.choice(JERSEY_IDS),

        # Optional features (probability-controlled)
        "EyeLine":    _optional(EYELINE_IDS, "eyeLine_pct"),
        "HairBG":     _optional(HAIRBG_IDS, "hairBg_pct"),
        "FacialHair": _optional(FACIALHAIR_IDS, "facialHair_pct"),
        "Glasses":    _optional(GLASSES_IDS, "glasses_pct"),
        "Accessories": _optional(ACCESSORIES_IDS, "accessories_pct"),
        "MiscLine":   _optional(MISCLINE_IDS, "miscLine_pct"),
        "SmileLine":  _optional(SMILELINE_IDS, "smileLine_pct"),

        # Sizing / angles
        "BodySize":      _ranged("BodySize"),
        "EarSize":       _ranged("EarSize"),
        "FaceSize":      _ranged("FaceSize"),
        "NoseSize":      _ranged("NoseSize"),
        "SmileLineSize": _ranged("SmileLineSize"),
        "EyeAngle":      _ranged("EyeAngle"),
        "EyeBrowAngle":  _ranged("EyeBrowAngle"),

        # Head shave intensity
        "FacialHairShave": str(round(rng.uniform(*_SHAVE_RANGE), 2)),

        # Colors
        "SkinColor":  rng.choice(SKIN_COLORS),
        "HairColor":  rng.choice(HAIR_COLORS),

        # Flips
        "HairFlip":  rng.choice([True, False]),
        "NoseFlip":  rng.choice([True, False]),
        "MouthFlip": rng.choice([True, False]),
    }


def generate_faces_bulk(
    player_ids: List[int],
    config: Optional[Dict[str, float]] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Generate faces for a batch of players.

    Returns:
        {player_id: FaceDataResponse, ...}
    """
    return {pid: generate_face(pid, config) for pid in player_ids}


# ---------------------------------------------------------------------------
# DB config loader
# ---------------------------------------------------------------------------

def load_face_config(conn) -> Dict[str, float]:
    """
    Read the admin-adjustable face generation config from face_gen_config.

    Returns DEFAULT_FREQUENCIES if the table doesn't exist or has no rows.
    """
    try:
        row = conn.execute(
            text("SELECT config FROM face_gen_config WHERE id = 1")
        ).first()
        if row and row[0]:
            raw = row[0]
            if isinstance(raw, str):
                return json.loads(raw)
            return dict(raw)  # already parsed by driver
    except Exception:
        logger.debug("face_gen_config table not available, using defaults")
    return dict(DEFAULT_FREQUENCIES)
