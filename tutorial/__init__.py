# tutorial/__init__.py
import json
import os
import re

from flask import Blueprint, jsonify, request

tutorial_bp = Blueprint("tutorial", __name__)

_CONTENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "content",
    "baseball-tutorial",
)


def _load_manifest():
    manifest_path = os.path.join(_CONTENT_DIR, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_article_file(file_path):
    full_path = os.path.join(_CONTENT_DIR, file_path)
    if not os.path.isfile(full_path):
        return None
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_frontmatter(raw_md):
    """Extract YAML-like frontmatter and body from a markdown string."""
    frontmatter = {}
    body = raw_md
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw_md, re.DOTALL)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                frontmatter[key.strip()] = value.strip()
        body = raw_md[match.end():]
    return frontmatter, body


# ── 1. Manifest ───────────────────────────────────────────────────────
@tutorial_bp.get("/baseball/tutorial")
def get_manifest():
    """Return all categories + article metadata + glossary (no body content)."""
    manifest = _load_manifest()

    # Build the API response: enrich articles with lastUpdated from frontmatter
    categories = []
    for cat in manifest["categories"]:
        articles = []
        for art in cat.get("articles", []):
            raw = _read_article_file(art["file"])
            fm, _ = _parse_frontmatter(raw) if raw else ({}, "")
            articles.append({
                "id": art["id"],
                "title": art["title"],
                "summary": art["summary"],
                "order": art["order"],
                "tags": art.get("tags", []),
                "leagueFilter": art.get("leagueFilter"),
                "lastUpdated": fm.get("lastUpdated", art.get("lastUpdated")),
            })
        categories.append({
            "id": cat["id"],
            "title": cat["title"],
            "icon": cat["icon"],
            "description": cat["description"],
            "order": cat["order"],
            "leagueFilter": cat.get("leagueFilter"),
            "articles": articles,
        })

    return jsonify(categories=categories, glossary=manifest.get("glossary", {}))


# ── 2. Single Article ─────────────────────────────────────────────────
@tutorial_bp.get("/baseball/tutorial/<category_id>/<article_id>")
def get_article(category_id: str, article_id: str):
    """Return the full markdown content for a single article."""
    manifest = _load_manifest()

    # Find the category and article in the manifest
    cat = next((c for c in manifest["categories"] if c["id"] == category_id), None)
    if cat is None:
        return jsonify(error="not_found", message="Category not found"), 404

    art = next((a for a in cat.get("articles", []) if a["id"] == article_id), None)
    if art is None:
        return jsonify(error="not_found", message="Article not found"), 404

    raw = _read_article_file(art["file"])
    if raw is None:
        return jsonify(error="not_found", message="Article file missing"), 404

    fm, body = _parse_frontmatter(raw)

    # Resolve relatedArticles references to {categoryId, articleId, title}
    related = []
    for ref in art.get("relatedArticles", []):
        # ref format: "category-id/article-id"
        parts = ref.split("/", 1)
        if len(parts) == 2:
            ref_cat_id, ref_art_id = parts
            ref_cat = next(
                (c for c in manifest["categories"] if c["id"] == ref_cat_id), None
            )
            if ref_cat:
                ref_art = next(
                    (a for a in ref_cat.get("articles", []) if a["id"] == ref_art_id),
                    None,
                )
                if ref_art:
                    related.append({
                        "categoryId": ref_cat_id,
                        "articleId": ref_art_id,
                        "title": ref_art["title"],
                    })

    return jsonify(
        id=article_id,
        categoryId=category_id,
        title=art["title"],
        markdown=body,
        tags=art.get("tags", []),
        relatedArticles=related,
        lastUpdated=fm.get("lastUpdated", art.get("lastUpdated")),
    )


# ── 3. Search ─────────────────────────────────────────────────────────
@tutorial_bp.get("/baseball/tutorial/search")
def search_articles():
    """Simple server-side search across titles, summaries, tags, and body."""
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify(results=[])

    manifest = _load_manifest()
    terms = q.split()
    results = []

    for cat in manifest["categories"]:
        for art in cat.get("articles", []):
            score = 0.0
            title_lower = art["title"].lower()
            summary_lower = art["summary"].lower()
            tags_lower = " ".join(art.get("tags", [])).lower()

            # Score title matches highest
            for term in terms:
                if term in title_lower:
                    score += 0.4
                if term in summary_lower:
                    score += 0.3
                if term in tags_lower:
                    score += 0.2

            # Check body content for matches
            raw = _read_article_file(art["file"])
            snippet = ""
            if raw:
                _, body = _parse_frontmatter(raw)
                body_lower = body.lower()
                for term in terms:
                    if term in body_lower:
                        score += 0.1
                        # Extract a snippet around the first match
                        if not snippet:
                            idx = body_lower.index(term)
                            start = max(0, idx - 60)
                            end = min(len(body), idx + 80)
                            snippet = "..." + body[start:end].strip() + "..."

            if score > 0:
                results.append({
                    "categoryId": cat["id"],
                    "articleId": art["id"],
                    "title": art["title"],
                    "summary": art["summary"],
                    "matchSnippet": snippet,
                    "score": round(score, 2),
                })

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)
    return jsonify(results=results)
