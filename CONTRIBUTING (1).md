# Contributing to Regulatory Change Tracker

Thank you for your interest in contributing. This tool exists to give financial institutions, compliance teams, and fintech developers a free, practical way to monitor U.S. regulatory activity across six agencies without proprietary subscriptions or manual checking.

Contributions from anyone — compliance professionals, developers, policy researchers, or institutions using the tool — are welcome.

---

## What We Are Looking For

### High-priority contributions

- **Additional agency feeds** — U.S. state regulators (NYDFS, DFPI, etc.), international equivalents (FCA, ESMA, MAS), or other federal agencies with financial services oversight (FTC, DOJ, HUD)
- **Topic taxonomy improvements** — Better keyword sets for detecting cross-agency activity. False positives (items tagged with irrelevant topics) and false negatives (items that should be tagged but are not) are both useful to report
- **Output delivery** — Email digest, Slack webhook, or Teams webhook delivery options
- **Historical archive** — Store results to a database or flat file so users can run trend analysis over time
- **Comment period tracker** — Surface proposed rules with comment deadlines approaching in the next 7/14/30 days

### Bug reports and feed issues

If a regulatory agency feed URL breaks or stops returning results, open an issue using the [Feed Issue template](.github/ISSUE_TEMPLATE/feed-issue.md). Include the agency, the feed URL, and any error message.

If an item is incorrectly categorized (for example, a final rule tagged as "Guidance"), open an issue with the item title, the current tag, and what it should be tagged as.

---

## How to Contribute

### 1. Fork the repository

Click "Fork" on GitHub. Clone your fork locally:

```bash
git clone https://github.com/YOUR-USERNAME/regulatory-change-tracker
cd regulatory-change-tracker
```

### 2. Set up your environment

```bash
pip install -r requirements.txt
pip install pytest  # for running tests
```

### 3. Make your changes

Follow the existing patterns in `src/tracker.py`:

- **Adding an agency:** Add an entry to the `AGENCY_FEEDS` dictionary following the existing format. Test that the feed URL returns results with `python tracker.py --agencies your-new-key`.
- **Adding topic keywords:** Add to the `TOPIC_KEYWORDS` dictionary. Keyword matching is case-insensitive.
- **Adding output formats:** Add a `format_<name>` function and add the option to the `--format` argument choices.

### 4. Test your changes

```bash
# Run the tracker with your new agency or feature
python src/tracker.py --agencies your-new-key --days 7

# Run any existing tests
pytest tests/
```

### 5. Submit a pull request

Push your branch and open a pull request. In the description:
- Briefly explain what you changed and why
- If you added an agency, note the agencies' full name and the feed URL
- If you changed category or topic detection, include a before/after example

---

## Adoption Reports

If your institution has deployed this tool — even in a limited or experimental way — we would appreciate hearing about it. Open an issue using the [Adoption Report template](.github/ISSUE_TEMPLATE/adoption-report.md).

Adoption reports serve two purposes: they help improve the tool based on real usage, and they contribute to the evidence base that open-source financial infrastructure serves institutions beyond a single employer.

---

## Questions

Open an issue with the "Question" label. There are no stupid questions.

---

*Maintained by [Sujatha Iyer](https://github.com/sujiyer)*
