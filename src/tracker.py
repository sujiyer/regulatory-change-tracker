"""
Regulatory Change Tracker for Financial Services
-------------------------------------------------
Monitors six U.S. financial regulatory agencies and produces a structured
digest of new rules, guidance documents, enforcement actions, and proposed
rulemaking.

Agencies: CFPB, FDIC, Federal Reserve, FinCEN, OCC, NCUA

Usage:
    python tracker.py                          # all agencies, last 30 days
    python tracker.py --agencies cfpb,occ      # specific agencies
    python tracker.py --days 7                 # last 7 days
    python tracker.py --topic "AI"             # filter by keyword
    python tracker.py --cross-agency           # show cross-agency topic overlap
    python tracker.py --output digest.md       # save to file
    python tracker.py --format json            # JSON output

Author: Sujatha Iyer (github.com/sujiayer)
License: MIT
"""

import argparse
import json
import sys
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional
from collections import defaultdict

try:
    import feedparser
except ImportError:
    sys.exit("Install required packages: pip install feedparser requests beautifulsoup4")

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Install required packages: pip install feedparser requests beautifulsoup4")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RegulatoryItem:
    agency: str
    title: str
    published: str              # ISO date string
    category: str               # "final rule", "proposed rule", "guidance", etc.
    url: str
    summary: str = ""
    comment_deadline: str = ""  # for proposed rules
    topics: list = field(default_factory=list)   # detected topic tags


# ---------------------------------------------------------------------------
# Agency feed definitions
# ---------------------------------------------------------------------------

AGENCY_FEEDS = {
    "cfpb": {
        "name": "CFPB",
        "full_name": "Consumer Financial Protection Bureau",
        "feeds": [
            "https://www.consumerfinance.gov/about-us/newsroom/feed/",
            "https://www.consumerfinance.gov/policy-compliance/rulemaking/final-rules/rss/",
        ],
        "focus": "Consumer protection, open banking, credit reporting, debt collection",
    },
    "fdic": {
        "name": "FDIC",
        "full_name": "Federal Deposit Insurance Corporation",
        "feeds": [
            "https://www.fdic.gov/news/financial-institution-letters/rss.xml",
            "https://www.fdic.gov/regulations/applications/rss.xml",
        ],
        "focus": "Bank supervision, deposit insurance, fintech guidance",
    },
    "federalreserve": {
        "name": "Federal Reserve",
        "full_name": "Board of Governors of the Federal Reserve System",
        "feeds": [
            "https://www.federalreserve.gov/feeds/press_all.xml",
        ],
        "focus": "Monetary policy, bank supervision, payment systems",
    },
    "fincen": {
        "name": "FinCEN",
        "full_name": "Financial Crimes Enforcement Network",
        "feeds": [
            "https://www.fincen.gov/rss.xml",
        ],
        "focus": "AML, KYC, BSA compliance, beneficial ownership",
    },
    "occ": {
        "name": "OCC",
        "full_name": "Office of the Comptroller of the Currency",
        "feeds": [
            "https://occ.gov/tools-forms/tools/rss/occ-news.xml",
        ],
        "focus": "National bank charters, fintech guidance, model risk",
    },
    "ncua": {
        "name": "NCUA",
        "full_name": "National Credit Union Administration",
        "feeds": [
            "https://www.ncua.gov/rss.xml",
        ],
        "focus": "Credit union supervision, share insurance, CDFI credit unions",
    },
}

# ---------------------------------------------------------------------------
# Topic detection keywords
# ---------------------------------------------------------------------------

TOPIC_KEYWORDS = {
    "AI Governance": [
        "artificial intelligence", "machine learning", "model risk", "algorithmic",
        "explainability", "adverse action", "ai", "automated decision", "black box",
        "model validation", "model drift",
    ],
    "Open Banking": [
        "section 1033", "open banking", "consumer data rights", "data portability",
        "api", "personal financial data", "1033",
    ],
    "AML / KYC": [
        "anti-money laundering", "know your customer", "kyc", "aml", "bsa",
        "beneficial ownership", "customer due diligence", "cdd", "cip",
        "suspicious activity", "sar", "fincen",
    ],
    "Financial Inclusion": [
        "unbanked", "underbanked", "cdfi", "community development", "low income",
        "underserved", "financial access", "credit desert",
    ],
    "Cybersecurity": [
        "cybersecurity", "data breach", "third party risk", "vendor risk",
        "operational resilience", "dora", "ransomware",
    ],
    "Credit / Fair Lending": [
        "fair lending", "ecoa", "fair housing", "disparate impact", "credit denial",
        "adverse action", "redlining", "cra", "community reinvestment",
    ],
    "Crypto / Digital Assets": [
        "cryptocurrency", "digital asset", "stablecoin", "defi", "blockchain",
        "crypto", "cbdc", "central bank digital",
    ],
    "Payments": [
        "payment", "instant payment", "real-time payment", "rtp", "ach",
        "wire transfer", "remittance", "faster payments",
    ],
}

# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "Final Rule": ["final rule", "final regulations", "effective date"],
    "Proposed Rule": ["proposed rule", "notice of proposed rulemaking", "nprm", "comment period", "request for comment"],
    "Guidance": ["guidance", "advisory", "bulletin", "letter", "interpretive letter", "faq", "supervisory letter"],
    "Enforcement Action": ["enforcement action", "consent order", "cease and desist", "civil money penalty", "cmp", "settlement"],
    "Consumer Alert": ["consumer alert", "warning", "scam alert", "fraud alert"],
    "Research / Report": ["report", "research", "study", "data point", "survey"],
    "Announcement": ["announcement", "press release", "statement"],
}


def detect_category(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return category
    return "General"


def detect_topics(title: str, summary: str) -> list:
    text = (title + " " + summary).lower()
    detected = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(k in text for k in keywords):
            detected.append(topic)
    return detected


def parse_date(entry) -> Optional[datetime]:
    """Try multiple date fields from a feed entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Feed fetching
# ---------------------------------------------------------------------------

def fetch_agency(agency_key: str, since: datetime, session: requests.Session) -> tuple[list, list]:
    """
    Returns (items, errors) for the given agency.
    Tries each configured feed URL in order and aggregates results.
    """
    config = AGENCY_FEEDS[agency_key]
    items = []
    errors = []
    seen_urls = set()

    for feed_url in config["feeds"]:
        try:
            # Use requests with timeout so we do not hang on slow government sites
            response = session.get(feed_url, timeout=15)
            response.raise_for_status()
            parsed = feedparser.parse(response.text)
        except requests.exceptions.RequestException as e:
            errors.append(f"[{config['name']}] Could not reach {feed_url}: {e}")
            continue
        except Exception as e:
            errors.append(f"[{config['name']}] Parse error on {feed_url}: {e}")
            continue

        for entry in parsed.entries:
            pub_dt = parse_date(entry)
            if pub_dt is None:
                # Cannot determine date; skip to avoid false positives
                continue
            if pub_dt < since:
                continue

            url = getattr(entry, "link", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = getattr(entry, "title", "(no title)")
            summary_raw = getattr(entry, "summary", "")
            # Strip HTML tags from summary if present
            summary = BeautifulSoup(summary_raw, "html.parser").get_text(separator=" ").strip()
            summary = re.sub(r"\s+", " ", summary)[:400]  # truncate for digest

            item = RegulatoryItem(
                agency=config["name"],
                title=title,
                published=pub_dt.strftime("%Y-%m-%d"),
                category=detect_category(title, summary),
                url=url,
                summary=summary,
                topics=detect_topics(title, summary),
            )
            items.append(item)

    # Sort newest-first
    items.sort(key=lambda x: x.published, reverse=True)
    return items, errors


def fetch_all(agency_keys: list, since: datetime) -> tuple[list, list]:
    """Fetch from all requested agencies. Returns (items, errors)."""
    all_items = []
    all_errors = []
    session = requests.Session()
    session.headers.update({"User-Agent": "RegulatoryChangeTracker/1.0 (github.com/sujiayer)"})

    for key in agency_keys:
        items, errors = fetch_agency(key, since, session)
        all_items.extend(items)
        all_errors.extend(errors)

    all_items.sort(key=lambda x: x.published, reverse=True)
    return all_items, all_errors


# ---------------------------------------------------------------------------
# Cross-agency analysis
# ---------------------------------------------------------------------------

def find_cross_agency_topics(items: list) -> dict:
    """
    Returns a dict of topic → set of agencies active on that topic.
    Only includes topics where more than one agency is active.
    """
    topic_agencies = defaultdict(set)
    for item in items:
        for topic in item.topics:
            topic_agencies[topic].add(item.agency)

    return {t: agencies for t, agencies in topic_agencies.items() if len(agencies) > 1}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_markdown(items: list, errors: list, args, cross_agency: dict) -> str:
    lines = []
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"# Regulatory Digest — Generated {run_date}")
    lines.append(f"**Agencies:** {', '.join([AGENCY_FEEDS[k]['name'] for k in args.agency_keys])}")
    lines.append(f"**Period:** Last {args.days} days")
    if args.topic:
        lines.append(f"**Topic filter:** {args.topic}")
    lines.append("")

    if not items:
        lines.append("*No new regulatory publications matched your filters.*")
    else:
        # Group by category
        by_category = defaultdict(list)
        for item in items:
            by_category[item.category].append(item)

        # Order categories
        category_order = [
            "Final Rule", "Proposed Rule", "Guidance", "Enforcement Action",
            "Consumer Alert", "Research / Report", "Announcement", "General"
        ]

        for cat in category_order:
            cat_items = by_category.get(cat, [])
            if not cat_items:
                continue
            lines.append(f"## {cat}s ({len(cat_items)} new)")
            lines.append("")
            for item in cat_items:
                lines.append(f"### [{item.agency}] {item.title}")
                lines.append(f"**Published:** {item.published}")
                if item.comment_deadline:
                    lines.append(f"**Comment Deadline:** {item.comment_deadline}")
                if item.topics:
                    lines.append(f"**Topics:** {', '.join(item.topics)}")
                if item.summary:
                    lines.append(f"> {item.summary}")
                lines.append(f"[Read more]({item.url})")
                lines.append("")

    # Cross-agency section
    if cross_agency:
        lines.append("---")
        lines.append("## Cross-Agency Activity")
        lines.append("")
        for topic, agencies in sorted(cross_agency.items()):
            lines.append(f"**{topic}**")
            lines.append(f"Active agencies: {', '.join(sorted(agencies))}")
            lines.append("")

    # Errors
    if errors:
        lines.append("---")
        lines.append("## Feed Errors")
        lines.append("*The following feeds could not be reached. Results from these agencies may be incomplete.*")
        lines.append("")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by the [Regulatory Change Tracker](https://github.com/sujiayer/regulatory-change-tracker)*")

    return "\n".join(lines)


def format_json(items: list, errors: list, cross_agency: dict) -> str:
    output = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "item_count": len(items),
        "items": [asdict(i) for i in items],
        "cross_agency_topics": {t: list(a) for t, a in cross_agency.items()},
        "errors": errors,
    }
    return json.dumps(output, indent=2)


def format_csv(items: list) -> str:
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Agency", "Title", "Published", "Category", "Topics", "URL", "Summary"])
    for item in items:
        writer.writerow([
            item.agency,
            item.title,
            item.published,
            item.category,
            "; ".join(item.topics),
            item.url,
            item.summary,
        ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Regulatory Change Tracker for U.S. Financial Services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tracker.py
  python tracker.py --agencies cfpb,fincen --days 7
  python tracker.py --topic AI --cross-agency
  python tracker.py --format json --output digest.json
        """,
    )
    p.add_argument(
        "--agencies",
        default="all",
        help=(
            "Comma-separated agency keys: cfpb, fdic, federalreserve, fincen, occ, ncua. "
            "Default: all"
        ),
    )
    p.add_argument("--days", type=int, default=30, help="Number of days to look back (default: 30)")
    p.add_argument("--topic", default=None, help="Filter results to items containing this keyword")
    p.add_argument("--cross-agency", action="store_true", help="Include cross-agency topic analysis")
    p.add_argument(
        "--format",
        choices=["markdown", "json", "csv"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    p.add_argument("--output", default=None, help="Save output to this file path (default: stdout)")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Resolve agency keys
    if args.agencies.strip().lower() == "all":
        agency_keys = list(AGENCY_FEEDS.keys())
    else:
        requested = [k.strip().lower() for k in args.agencies.split(",")]
        invalid = [k for k in requested if k not in AGENCY_FEEDS]
        if invalid:
            parser.error(
                f"Unknown agency key(s): {', '.join(invalid)}. "
                f"Valid keys: {', '.join(AGENCY_FEEDS.keys())}"
            )
        agency_keys = requested

    args.agency_keys = agency_keys

    # Compute date cutoff
    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    print(f"Fetching from {len(agency_keys)} agencies (last {args.days} days)...", file=sys.stderr)
    items, errors = fetch_all(agency_keys, since)

    # Apply topic filter if requested
    if args.topic:
        keyword = args.topic.lower()
        items = [
            i for i in items
            if keyword in i.title.lower() or keyword in i.summary.lower()
            or any(keyword in t.lower() for t in i.topics)
        ]

    print(f"Found {len(items)} items.", file=sys.stderr)
    if errors:
        print(f"{len(errors)} feed error(s). See output for details.", file=sys.stderr)

    # Cross-agency analysis
    cross_agency = find_cross_agency_topics(items) if args.cross_agency else {}

    # Format output
    if args.format == "markdown":
        output = format_markdown(items, errors, args, cross_agency)
    elif args.format == "json":
        output = format_json(items, errors, cross_agency)
    elif args.format == "csv":
        output = format_csv(items)
    else:
        output = format_markdown(items, errors, args, cross_agency)

    # Write output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
