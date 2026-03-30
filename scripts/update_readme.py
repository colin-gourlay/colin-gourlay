#!/usr/bin/env python3
"""Auto-update README.md with live GitHub data (recent activity and repositories)."""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Optional

GITHUB_USERNAME = "colin-gourlay"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")

ACTIVITY_START = "<!-- ACTIVITY_START -->"
ACTIVITY_END = "<!-- ACTIVITY_END -->"
REPOS_START = "<!-- REPOS_START -->"
REPOS_END = "<!-- REPOS_END -->"
STARS_START = "<!-- STARS_START -->"
STARS_END = "<!-- STARS_END -->"


def github_api(endpoint: str) -> object:
    """Call the GitHub REST API and return parsed JSON."""
    url = f"https://api.github.com{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def short_date(iso_str: str) -> str:
    """Convert an ISO 8601 string to a short human-readable date."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y")
    except (ValueError, AttributeError):
        return iso_str[:10]


def format_event(event: dict) -> Optional[str]:
    """Return a markdown line for a single GitHub event, or None to skip."""
    event_type = event.get("type", "")
    repo_name = event.get("repo", {}).get("name", "")
    repo_url = f"https://github.com/{repo_name}"
    payload = event.get("payload", {})
    date = short_date(event.get("created_at", ""))

    if event_type == "PushEvent":
        commits = payload.get("commits", [])
        if commits:
            msg = commits[-1].get("message", "").split("\n")[0][:72]
            return f"🔨 **Pushed** to [`{repo_name}`]({repo_url}) — _{msg}_ `{date}`"
        return f"🔨 **Pushed** to [`{repo_name}`]({repo_url}) `{date}`"

    if event_type == "PullRequestEvent":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        pr_title = pr.get("title", "")[:72]
        merged = pr.get("merged", False)
        verb = "Merged" if merged else action.capitalize()
        if action in ("opened", "closed", "reopened"):
            return f"🔀 **{verb} PR** in [`{repo_name}`]({repo_url}) — _{pr_title}_ `{date}`"

    if event_type == "CreateEvent":
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        if ref_type == "repository":
            return f"🆕 **Created repository** [`{repo_name}`]({repo_url}) `{date}`"
        if ref_type in ("branch", "tag"):
            return f"🌿 **Created {ref_type}** `{ref}` in [`{repo_name}`]({repo_url}) `{date}`"

    if event_type == "ReleaseEvent":
        tag = payload.get("release", {}).get("tag_name", "")
        return f"🚀 **Released** `{tag}` in [`{repo_name}`]({repo_url}) `{date}`"

    if event_type == "IssuesEvent":
        action = payload.get("action", "")
        issue_title = payload.get("issue", {}).get("title", "")[:72]
        if action in ("opened", "closed"):
            return f"🐛 **{action.capitalize()} issue** in [`{repo_name}`]({repo_url}) — _{issue_title}_ `{date}`"

    if event_type == "ForkEvent":
        forkee = payload.get("forkee", {}).get("full_name", "")
        return f"🍴 **Forked** [`{repo_name}`]({repo_url}) → `{forkee}` `{date}`"

    return None


def build_activity_section(limit: int = 10) -> str:
    """Fetch public events and return a markdown block."""
    try:
        events = github_api(f"/users/{GITHUB_USERNAME}/events/public?per_page=50")
    except Exception as exc:
        print(f"Warning: could not fetch events: {exc}", file=sys.stderr)
        return "_Activity data temporarily unavailable._"

    lines: list[str] = []
    seen: set[str] = set()
    for event in events:
        formatted = format_event(event)
        if formatted and formatted not in seen:
            seen.add(formatted)
            lines.append(f"- {formatted}")
            if len(lines) >= limit:
                break

    return "\n".join(lines) if lines else "_No recent public activity found._"


def build_repos_section(limit: int = 8) -> str:
    """Fetch public owned repos (sorted by last push) and return a markdown block."""
    try:
        repos = github_api(
            f"/users/{GITHUB_USERNAME}/repos"
            "?type=owner&sort=pushed&direction=desc&per_page=30"
        )
    except Exception as exc:
        print(f"Warning: could not fetch repos: {exc}", file=sys.stderr)
        return "_Repository data temporarily unavailable._"

    lines: list[str] = []
    for repo in repos:
        if repo.get("fork") or repo.get("name") == GITHUB_USERNAME:
            continue
        name = repo.get("name", "")
        description = (repo.get("description") or "").strip()
        url = repo.get("html_url", "")
        language = repo.get("language") or ""
        stars = repo.get("stargazers_count", 0)

        line = f"[**{name}**]({url})"
        if description:
            line += f" — {description}"
        meta: list[str] = []
        if language:
            meta.append(f"`{language}`")
        if stars > 0:
            meta.append(f"⭐ {stars}")
        if meta:
            line += "  " + " ".join(meta)
        lines.append(f"- {line}")
        if len(lines) >= limit:
            break

    return "\n".join(lines) if lines else "_No public repositories found._"


def build_stars_section(recent_limit: int = 6, lang_limit: int = 8) -> str:
    """Fetch starred repos and return a markdown block with recent stars and language interests."""
    try:
        starred = github_api(
            f"/users/{GITHUB_USERNAME}/starred"
            "?sort=created&direction=desc&per_page=30"
        )
    except Exception as exc:
        print(f"Warning: could not fetch starred repos: {exc}", file=sys.stderr)
        return "_Starred repository data temporarily unavailable._"

    lang_counts: dict[str, int] = {}
    recent_lines: list[str] = []

    for repo in starred:
        language = (repo.get("language") or "").strip()
        if language:
            lang_counts[language] = lang_counts.get(language, 0) + 1

        if len(recent_lines) < recent_limit:
            name = repo.get("full_name", "")
            description = (repo.get("description") or "").strip()
            url = repo.get("html_url", "")
            stars = repo.get("stargazers_count", 0)

            line = f"[**{name}**]({url})"
            if description:
                line += f" — {description[:80]}"
            meta: list[str] = []
            if language:
                meta.append(f"`{language}`")
            if stars > 0:
                meta.append(f"⭐ {stars:,}")
            if meta:
                line += "  " + " ".join(meta)
            recent_lines.append(f"- {line}")

    parts: list[str] = []

    if recent_lines:
        parts.append("### 🕐 Recently Starred\n\n" + "\n".join(recent_lines))
    else:
        parts.append("### 🕐 Recently Starred\n\n_No recently starred repositories found._")

    if lang_counts:
        top_langs = sorted(lang_counts.items(), key=lambda x: -x[1])[:lang_limit]
        lang_badges = " · ".join(f"`{lang}` ×{count}" for lang, count in top_langs)
        parts.append("### 🗺️ Language Interests\n\n" + lang_badges)

    return "\n\n".join(parts)


def replace_section(content: str, start: str, end: str, inner: str) -> str:
    """Replace everything between start and end markers (inclusive) with new content."""
    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end),
        re.DOTALL,
    )
    replacement = f"{start}\n{inner}\n{end}"
    result, n = pattern.subn(replacement, content)
    if n == 0:
        print(f"Warning: markers not found — {start!r}", file=sys.stderr)
    return result


def main() -> None:
    if not GITHUB_TOKEN:
        print("Warning: GITHUB_TOKEN not set; unauthenticated API calls may be rate-limited.", file=sys.stderr)

    with open(README_PATH, encoding="utf-8") as fh:
        original = fh.read()

    timestamp = datetime.now(timezone.utc).strftime("%-d %B %Y at %H:%M UTC")

    print(f"Fetching recent activity for @{GITHUB_USERNAME}…")
    activity_md = build_activity_section()

    print(f"Fetching repositories for @{GITHUB_USERNAME}…")
    repos_md = build_repos_section()

    print(f"Fetching starred repositories for @{GITHUB_USERNAME}…")
    stars_md = build_stars_section()

    activity_block = (
        "## 📡 Recent Activity\n\n"
        f"{activity_md}\n\n"
        f"<sub>Last updated: {timestamp}</sub>"
    )
    repos_block = (
        "## 🗂️ Repositories\n\n"
        f"{repos_md}\n\n"
        f"<sub>Last updated: {timestamp}</sub>"
    )
    stars_block = (
        "## ⭐ Starred Repositories\n\n"
        f"{stars_md}\n\n"
        f"<sub>Last updated: {timestamp}</sub>"
    )

    updated = replace_section(original, ACTIVITY_START, ACTIVITY_END, activity_block)
    updated = replace_section(updated, REPOS_START, REPOS_END, repos_block)
    updated = replace_section(updated, STARS_START, STARS_END, stars_block)

    if updated == original:
        print("README.md is already up to date — nothing to commit.")
        return

    with open(README_PATH, "w", encoding="utf-8") as fh:
        fh.write(updated)
    print("README.md updated successfully.")


if __name__ == "__main__":
    main()
