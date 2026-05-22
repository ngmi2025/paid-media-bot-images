"""Render Notion-style colored tables as PNG images via headless Chromium.

Reusable across all the Slack-attachment images:
- Pacing & Tier per card
- ROAS tables
- CARD SPRINT summary
- CHANNEL SPRINT (5 sub-tables)

All rendering uses HTML+CSS to mimic Notion's light-mode table aesthetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

# Google Sheets default conditional-formatting palette (the "Light X 3" presets
# Mary uses in her Pacing & Tier Tracker sheet).
COLORS = {
    "default":   {"bg": "#FFFFFF", "text": "#000000"},
    "gray_bg":   {"bg": "#EFEFEF", "text": "#595959"},
    "red_bg":    {"bg": "#F4CCCC", "text": "#000000"},
    "orange_bg": {"bg": "#FCE5CD", "text": "#000000"},
    "yellow_bg": {"bg": "#FFF2CC", "text": "#000000"},
    "green_bg":  {"bg": "#D9EAD3", "text": "#000000"},
}

NOTION_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: Arial, "Helvetica Neue", Helvetica, sans-serif;
  font-size: 13px;
  color: #000000;
  background: #FFFFFF;
  padding: 16px;
}
body.compact { padding: 6px; }
body.compact .section-title {
  padding: 4px 8px;
  font-size: 10px;
  margin-bottom: 8px;
}
.section-title {
  display: inline-block;
  border: 1.5px solid #000000;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 700;
  color: #000000;
  margin-bottom: 12px;
}
.section-subtitle {
  font-size: 12px;
  color: #595959;
  font-style: italic;
  margin-bottom: 12px;
}
table {
  border-collapse: collapse;
  background: #FFFFFF;
  margin-bottom: 12px;
  border: 1.5px solid #000000;
}
body > *:last-child,
table:last-child {
  margin-bottom: 0 !important;
}
th, td {
  border: 1px solid #000000;
  padding: 3px 6px;
  text-align: center;
  vertical-align: middle;
  font-size: 9px;
  line-height: 1.2;
  font-weight: 700;
}
th {
  background: #FFFFFF;
  font-weight: 700;
  color: #000000;
  text-align: center;
}
td.label {
  text-align: left;
  font-weight: 700;
}
td.num { text-align: center; }
td.bold { font-weight: 700; }
td.red-bg    { background: #F4CCCC; color: #000000; }
td.orange-bg { background: #FCE5CD; color: #000000; }
td.yellow-bg { background: #FFF2CC; color: #000000; }
td.green-bg  { background: #D9EAD3; color: #000000; }
td.gray-bg   { background: #EFEFEF; color: #595959; font-weight: 400; }
.card-header-row td {
  font-weight: 700;
  text-align: left;
  padding-left: 14px;
}
.card-header-row td.green-bg,
.card-header-row td.red-bg,
.card-header-row td.yellow-bg { font-weight: 700; }
/* ROAS-block — compact (Mary's cells render small in Notion display) */
table.roas-block td.num,
table.roas-block th { text-align: right; padding: 2px 5px; font-size: 7px; }
table.roas-block td.label { text-align: left; padding: 2px 4px; font-weight: 700; font-size: 7px; }
table.roas-block .card-header-row td.label {
  text-align: right;
  padding-left: 14px;
  position: relative;
}
table.roas-block .card-header-row td.label .dot { float: left; }

/* CARD SPRINT wide table — Mary's distinct styling */
table.card-sprint {
  border: 1px solid #000;
}
table.card-sprint th {
  background: #CCCCCC;
  font-weight: 700;
  text-align: center;
  font-size: 12px;
  padding: 5px 10px;
  line-height: 1.2;
}
table.card-sprint th.blue-head {
  background: #CFE2F3;
}
table.card-sprint td {
  background: #FFFFFF;
  font-weight: 400;
  font-size: 12px;
  padding: 3px 10px;
}
table.card-sprint td.label { text-align: left; padding-left: 10px; font-weight: 400; }
table.card-sprint td.num { text-align: right; padding-right: 10px; }
table.card-sprint td.blue-cell { background: #CFE2F3; }
table.card-sprint tr.totals-row td { font-weight: 700; border-top: 2px solid #000; }
table.card-sprint tr.totals-row td.label { font-weight: 700; }

/* Channel Sprint — icon column on the left + same data shape */
table.channel-sprint td.channel-icon {
  background: #FFFFFF;
  vertical-align: middle;
  text-align: center;
  width: 130px;
  border-right: 1.5px solid #000;
  padding: 14px 8px;
}
table.channel-sprint .channel-label {
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 12px;
  color: #000;
}
table.channel-sprint .channel-glyph {
  display: inline-block;
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  width: 56px;
  height: 56px;
  border-radius: 12px;
  text-align: center;
  vertical-align: middle;
  padding-top: 14px;
}
table.channel-sprint .channel-glyph img.channel-logo {
  max-width: 56px;
  max-height: 56px;
  width: auto;
  height: auto;
  display: block;
  margin: 0 auto;
}
/* Wider logo box for the Meta wordmark which has long aspect ratio */
table.channel-sprint .channel-glyph img[alt="Meta"] {
  max-width: 80px;
}
.glyph-google  { background: #FFFFFF; color: #4285F4; font-family: "Arial", sans-serif; }
.glyph-meta    { background: #FFFFFF; color: #0866FF; font-family: "Arial", sans-serif; }
.glyph-bing    { background: #FFFFFF; color: #008372; font-family: "Arial", sans-serif; }
.glyph-organic { background: #FFFFFF; color: #34A853; }
.glyph-direct  { background: #FFFFFF; color: #F4B400; }

/* Bottom-of-page ROAS summary blocks — compact (target 30% smaller) */
table.bottom-roas {
  border: 1.5px solid #000;
  margin-bottom: 6px;
}
table.bottom-roas th {
  background: #FFFFFF;
  font-size: 8px;
  font-weight: 700;
  padding: 3px 5px;
  border: 1px solid #000;
  text-align: center;
  line-height: 1.2;
}
table.bottom-roas th.blue-head {
  background: #CFE2F3;
  color: #1F4E79;
}
table.bottom-roas td {
  font-size: 9px;
  padding: 3px 5px;
  border: 1px solid #000;
  text-align: center;
  font-weight: 700;
}

/* Mini Pacing table (inside NEXT STEPS bullets) — sized close to Mary's 868×364 */
.mini-label {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 4px;
}
table.mini-pacing {
  border: 1px solid #000;
}
table.mini-pacing th {
  background: #FFFFFF;
  font-size: 13px;
  font-weight: 700;
  padding: 6px 32px;
  text-align: right;
  border: 1px solid #000;
}
table.mini-pacing th.mini-channel {
  background: #CCCCCC;
  text-align: right;
  padding-right: 32px;
}
table.mini-pacing td {
  font-size: 13px;
  padding: 3px 32px;
  border: 1px solid #000;
  text-align: right;
}
table.mini-pacing td.label {
  background: #FFFFFF;
  font-weight: 700;
  text-align: left;
  padding-left: 32px;
}

/* Tier subtable — appended below the card's pacing table */
table.tier-subtable {
  margin-top: 4px;
  margin-bottom: 12px;
  margin-left: 60px;          /* indent so it aligns roughly with col 2 of pacing */
  border: 1.5px solid #000;
}
table.tier-subtable td,
table.tier-subtable th {
  font-size: 9px;
  padding: 4px 8px;
  border: 1px solid #000;
}
table.tier-subtable th {
  background: #FFFFFF;
  font-weight: 700;
  text-align: center;
}
table.tier-subtable td.tier-label {
  background: #FFFFFF;
  text-align: left;
  font-weight: 700;
  padding: 8px 12px;
}
table.tier-subtable td.tier-cell {
  font-size: 11px;
  text-align: center;
  color: #777;
  line-height: 1.25;
  font-weight: 400;
}
table.tier-subtable td.empty-cell {
  border: none;
  background: transparent;
  padding: 0;
}
.dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  margin-right: 8px;
  vertical-align: middle;
}
.dot.green  { background: #38A169; border: 1px solid #2F855A; }
.dot.yellow { background: #ECC94B; border: 1px solid #D69E2E; }
.dot.red    { background: #E53E3E; border: 1px solid #C53030; }
"""


def _color_class(color: str | None) -> str:
    if not color:
        return ""
    return {
        "red_bg": "red-bg",
        "orange_bg": "orange-bg",
        "yellow_bg": "yellow-bg",
        "green_bg": "green-bg",
        "gray_bg": "gray-bg",
    }.get(color, "")


def render_html_to_png(
    html: str,
    out_path: Path | str,
    viewport_width: int = 900,
    scale: float = 2.0,
) -> Path:
    """Render an HTML string to PNG via headless Chromium.

    Args:
        html: full HTML document (must include the body content)
        out_path: max page width in CSS px (content may render narrower)
        scale: device scale factor (2.0 = retina, sharper text)
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": viewport_width, "height": 800},
            device_scale_factor=scale,
        )
        page = context.new_page()
        page.set_content(html, wait_until="load")
        # Shrink body to its own content (no trailing whitespace on either axis),
        # then measure the exact rendered dimensions and clip the screenshot to them.
        dims = page.evaluate(
            """() => {
              const b = document.body;
              b.style.display = 'inline-block';
              b.style.width = 'fit-content';
              const r = b.getBoundingClientRect();
              return { w: Math.ceil(r.right), h: Math.ceil(r.bottom) };
            }"""
        )
        page.set_viewport_size({"width": dims["w"], "height": dims["h"]})
        page.screenshot(
            path=str(out_path),
            clip={"x": 0, "y": 0, "width": dims["w"], "height": dims["h"]},
        )
        browser.close()
    return out_path


# === Helpers for each report section ========================================

CARD_NAMES_FULL = {
    "ABP": "Amex Business Platinum",
    "ABG": "Amex Business Gold",
    "AP": "Amex Platinum",
    "AG": "Amex Gold",
    "BCP": "Blue Cash Preferred",
    "BCE": "Blue Cash Everyday",
}


def _wrap(content: str, body_class: str = "") -> str:
    body_attr = f" class='{body_class}'" if body_class else ""
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{NOTION_CSS}</style></head><body{body_attr}>{content}</body></html>"


def _render_tier_subtable(tiers: dict[str, Any]) -> str:
    """Build the HTML for a card's Tier subtable (matches Mary's structure).

    `tiers` dict shape:
        {
          header_label: "AP Tiers",
          dot_color: "yellow" | "green" | "red",
          notes: "*Goals edited: Min 350+ Stretch 500+" (optional),
          notes_bg: "green_bg",
          actuals: 219,
          pacing: 428,
          status: "Low Mid Achieved, Pacing to Top Mid",
          status_bg: "yellow_bg",
          breakpoints: [(name, range, bg), ...]   # 2-4 tiers
        }
    """
    n = len(tiers["breakpoints"])
    dot = tiers.get("dot_color", "yellow")
    label = tiers["header_label"]
    notes = tiers.get("notes", "")
    notes_cc = _color_class(tiers.get("notes_bg")) if notes else ""
    status = tiers.get("status", "")
    status_cc = _color_class(tiers.get("status_bg", "yellow_bg")) if status else ""

    # Grid width = max(4, 1 + n)
    n_total = max(4, 1 + n)
    span = n_total - 3  # columns remaining after [label][Actuals][Pacing]

    # Row 1: header row
    note_cell = (
        f"<td class='label {notes_cc}' colspan='{span}'>{notes}</td>"
        if notes
        else f"<td colspan='{span}' class='empty-cell'></td>"
    )
    row1 = (
        "<tr>"
        f"<td class='tier-label'><span class='dot {dot}'></span>{label}</td>"
        "<th>Actuals</th><th>Pacing</th>"
        f"{note_cell}"
        "</tr>"
    )

    # Row 2: totals
    status_cell = (
        f"<td class='label {status_cc}' colspan='{span}'>{status}</td>"
        if status
        else f"<td colspan='{span}' class='empty-cell'></td>"
    )
    row2 = (
        "<tr>"
        "<td class='tier-label'>Totals</td>"
        f"<td class='num bold'>{tiers['actuals']}</td>"
        f"<td class='num bold'>{tiers['pacing']}</td>"
        f"{status_cell}"
        "</tr>"
    )

    # Row 3: tier breakpoints (col 0 empty, then n cells, pad with empties)
    row3_cells = ["<td class='empty-cell'></td>"]
    for name, rng, bg in tiers["breakpoints"]:
        cc = _color_class(bg)
        row3_cells.append(f"<td class='tier-cell {cc}'>{name}<br>{rng}</td>")
    while len(row3_cells) < n_total:
        row3_cells.append("<td class='empty-cell'></td>")
    row3 = "<tr>" + "".join(row3_cells) + "</tr>"

    return f"<table class='tier-subtable'>{row1}{row2}{row3}</table>"


def _cell(value: str, color: str | None = None, *, label: bool = False) -> str:
    """Render a single <td>. `color` is one of red_bg/yellow_bg/green_bg/gray_bg or None."""
    classes = []
    if label:
        classes.append("label")
    else:
        classes.append("num")
    classes.append("bold")
    cc = _color_class(color)
    if cc:
        classes.append(cc)
    return f"<td class='{' '.join(classes)}'>{value}</td>"


def render_pacing_tables(
    cards: list[dict[str, Any]],
    out_path: Path | str,
    *,
    period_label: str = "this Month",
    include_title: bool = True,
) -> Path:
    """Render a subset of pacing tables as one image (matches Mary's grouping).

    Mary's structure: each card is its own bordered table whose FIRST ROW is the
    card-name cell (with colored dot) spanning into the header row. Title above
    is in a thin black-bordered label, but only appears on the first image.

    Each card dict must have:
        card_code, card_color ("green"/"yellow"/"red"),
        rows: list of {label, last, last_color, ud, ud_color, current,
                       current_color, current_per_day, current_per_day_color,
                       needed_per_day, needed_per_day_color}
        tiers: optional tier-subtable dict (see _render_tier_subtable)
    """
    blocks: list[str] = []
    if include_title:
        blocks.append("<div class='section-title'>Pacing &amp; Tier Tracking</div>")
    for card in cards:
        code = card["card_code"]
        dot_class = card["card_color"]
        # Card-name cell uses the matching pale Google Sheets background.
        name_bg = {"green": "green_bg", "yellow": "yellow_bg", "red": "red_bg"}.get(dot_class, None)
        name_cc = _color_class(name_bg)
        name_cell = (
            f"<td class='label {name_cc}'>"
            f"<span class='dot {dot_class}'></span>{code}</td>"
        )
        header_row = (
            f"<tr class='card-header-row'>{name_cell}"
            f"<th>Last</th><th>Up ^v Down</th><th>Current</th>"
            f"<th>Current/Day</th><th>Needed/Day in {period_label}</th></tr>"
        )
        body_rows = []
        for r in card["rows"]:
            body_rows.append(
                "<tr>"
                + _cell(r["label"], label=True)
                + _cell(r.get("last", "n/a"), r.get("last_color"))
                + _cell(r.get("ud", "n/a"), r.get("ud_color"))
                + _cell(r["current"], r.get("current_color"))
                + _cell(r.get("current_per_day", ""), r.get("current_per_day_color") or "gray_bg")
                + _cell(r.get("needed_per_day", ""), r.get("needed_per_day_color") or "gray_bg")
                + "</tr>"
            )
        blocks.append(f"<table>{header_row}{''.join(body_rows)}</table>")
        tiers = card.get("tiers")
        if tiers:
            blocks.append(_render_tier_subtable(tiers))
    return render_html_to_png(_wrap("\n".join(blocks)), out_path, viewport_width=1400)


def render_roas_section(channels: list[dict[str, Any]], out_path: Path | str) -> Path:
    """Render the mid-page ROAS section (title + 3 channel sub-tables).

    Each channel dict: {
        name: "Google"|"Meta"|"Bing",
        color: "green"|"red"|"yellow",   # dot color, also drives name-cell bg
        rows: [
          {metric, last, last_color, ud, ud_color, current, current_color}
        ]
    }
    """
    blocks: list[str] = ["<div class='section-title'>ROAS</div>"]
    for ch in channels:
        dot_class = ch.get("color", "green")
        name_bg = {"green": "green_bg", "yellow": "yellow_bg", "red": "red_bg"}.get(dot_class)
        name_cc = _color_class(name_bg)
        name_cell = (
            f"<td class='label {name_cc}'>"
            f"<span class='dot {dot_class}'></span>{ch['name']}</td>"
        )
        header_row = (
            f"<tr class='card-header-row'>{name_cell}"
            f"<th>Last</th><th>^v</th><th>Current</th></tr>"
        )
        body_rows = []
        for r in ch["rows"]:
            body_rows.append(
                "<tr>"
                + _cell(r["metric"], label=True)
                + _cell(r.get("last", "n/a"), r.get("last_color"))
                + _cell(r.get("ud", "n/a"), r.get("ud_color"))
                + _cell(r["current"], r.get("current_color"))
                + "</tr>"
            )
        blocks.append(f"<table class='roas-block'>{header_row}{''.join(body_rows)}</table>")
        blocks.append("<div style='height:14px;'></div>")
    # Remove the trailing spacer so the crop is tight
    if blocks and blocks[-1].endswith("height:14px;'></div>"):
        blocks.pop()
    return render_html_to_png(_wrap("\n".join(blocks), body_class="compact"), out_path, viewport_width=900)


def _gradient_color_for_pct(pct: float | None) -> str:
    """Google Sheets color-scale gradient used by Mary on % columns.

    Anchors: 0%=#E06666 (deep red), 85%=#FFD966 (deep yellow), 130%=#93C47D (deep green).
    Returns an inline hex (used directly in style="background:#XXXXXX;") because
    the gradient is per-value, not from the 4 named tokens.
    """
    if pct is None:
        return "#EFEFEF"  # gray for n/a
    def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    # 3-stop gradient: 0% red -> 85% yellow -> 130% green (clamped beyond)
    p = max(0.0, min(pct, 130.0))
    if p <= 85.0:
        t = p / 85.0
        rgb = lerp((224, 102, 102), (255, 217, 102), t)
    else:
        t = (p - 85.0) / (130.0 - 85.0)
        rgb = lerp((255, 217, 102), (147, 196, 125), t)
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _gradient_cell(value: str, pct: float | None) -> str:
    bg = _gradient_color_for_pct(pct)
    return f"<td class='num bold' style='background:{bg};color:#000;'>{value}</td>"


def render_card_sprint_summary(rows: list[dict[str, Any]], out_path: Path | str, *, month: str = "May") -> Path:
    """Render the CARD SPRINT wide summary table (matches Mary's layout).

    Each row dict:
      {card_code, cpa, min, tier, stretch, mtd, pacing,
       pct_min, pct_min_value, pct_stretch, pct_stretch_value}
    Where pct_*_value is a float (for gradient coloring) and pct_* is the
    formatted display string (e.g. "210%" or "n/a").
    A final dict with card_code="Totals" is rendered as the Totals row.
    """
    # No section title above this one — Mary's report uses the column row as the header.
    thead = (
        "<tr class='card-sprint-head'>"
        "<th>Card</th><th>Month</th><th>CPA</th>"
        "<th class='blue-head'>Minimum Threshold</th>"
        "<th class='blue-head'>Tier Target</th>"
        "<th class='blue-head'>Stretch Goal</th>"
        "<th>Actuals MTD</th><th>Pacing</th>"
        "<th>Pacing vs. Minimum</th><th>Pacing vs. Stretch Goal %</th>"
        "</tr>"
    )
    body_html: list[str] = []
    for r in rows:
        is_totals = r.get("card_code") == "Totals"
        row_cls = " class='totals-row'" if is_totals else ""
        card_label = "Totals" if is_totals else CARD_NAMES_FULL.get(r["card_code"], r["card_code"])
        body_html.append(
            f"<tr{row_cls}>"
            f"<td class='label'>{card_label}</td>"
            f"<td class='label'>{r.get('month', month) if not is_totals else ''}</td>"
            f"<td class='num'>{r.get('cpa', '')}</td>"
            f"<td class='num blue-cell'>{r.get('min', 'n/a')}</td>"
            f"<td class='num blue-cell'>{r.get('tier', 'n/a')}</td>"
            f"<td class='num blue-cell'>{r.get('stretch', 'n/a')}</td>"
            f"<td class='num'>{r.get('mtd', '')}</td>"
            f"<td class='num'>{r.get('pacing', '')}</td>"
            + _gradient_cell(r.get("pct_min", "n/a"), r.get("pct_min_value"))
            + _gradient_cell(r.get("pct_stretch", "n/a"), r.get("pct_stretch_value"))
            + "</tr>"
        )
    table_html = f"<table class='card-sprint'>{thead}{''.join(body_html)}</table>"
    return render_html_to_png(_wrap(table_html, body_class="compact"), out_path, viewport_width=1400)


# Real brand logos as base64-encoded SVG data URIs (no network dependency at render time).
# Google "G" is the official multi-color G; Meta is the gradient infinity wordmark;
# Bing is the blue/teal "b" icon. Organic + Direct use emoji approximations.
_GOOGLE_G_SVG_B64 = (
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0OCA0OCI+CjxwYXRoIGZpbGw9IiM0Mjg1RjQiIGQ9Ik00NS4xMiAyNC41YzAtMS41Ni0uMTQtMy4wNi0uNC00LjVIMjR2OC41MWgxMS44NGMtLjUxIDIuNzUtMi4wNiA1LjA4LTQuMzkgNi42NHY1LjUyaDcuMTFjNC4xNi0zLjgzIDYuNTYtOS40NyA2LjU2LTE2LjE3eiIvPgo8cGF0aCBmaWxsPSIjMzRBODUzIiBkPSJNMjQgNDZjNS45NCAwIDEwLjkyLTEuOTcgMTQuNTYtNS4zM2wtNy4xMS01LjUyYy0xLjk3IDEuMzItNC40OSAyLjEtNy40NSAyLjEtNS43MyAwLTEwLjU4LTMuODctMTIuMzEtOS4wN0g0LjM0djUuN0M3Ljk2IDQxLjA3IDE1LjQgNDYgMjQgNDZ6Ii8+CjxwYXRoIGZpbGw9IiNGQkJDMDUiIGQ9Ik0xMS42OSAyOC4xOEMxMS4yNSAyNi44NiAxMSAyNS40NSAxMSAyNHMuMjUtMi44Ni42OS00LjE4di01LjdINC4zNEMyLjg1IDE3LjA5IDIgMjAuNDUgMiAyNGMwIDMuNTUuODUgNi45MSAyLjM0IDkuODhsNy4zNS01Ljd6Ii8+CjxwYXRoIGZpbGw9IiNFQTQzMzUiIGQ9Ik0yNCAxMC43NWMzLjIzIDAgNi4xMyAxLjExIDguNDEgMy4yOWw2LjMxLTYuMzFDMzQuOTEgNC4xOCAyOS45MyAyIDI0IDIgMTUuNCAyIDcuOTYgNi45MyA0LjM0IDE0LjEybDcuMzUgNS43QzEzLjQyIDE0LjYyIDE4LjI3IDEwLjc1IDI0IDEwLjc1eiIvPgo8L3N2Zz4="
)
_META_SVG_B64 = (
    "PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz4KPHN2ZyB4bWxuczpyZGY9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkvMDIvMjItcmRmLXN5bnRheC1ucyMiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHhtbG5zOmNjPSJodHRwOi8vY3JlYXRpdmVjb21tb25zLm9yZy9ucyMiIHdpZHRoPSI5NDgiIGhlaWdodD0iMTkxIj4KPGRlc2M+TG9nbyBvZiBNZXRhIFBsYXRmb3JtcyAtLSBHcmFwaGljIGNyZWF0ZWQgYnkgRGV0bWFyIE93ZW48L2Rlc2M+CjxkZWZzPgo8bGluZWFyR3JhZGllbnQgaWQ9IkdyYWRfTG9nbzEiIHgxPSI2MSIgeTE9IjExNyIgeDI9IjI1OSIgeTI9IjEyNyIgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiPgo8c3RvcCBzdHlsZT0ic3RvcC1jb2xvcjojMDA2NGUxIiBvZmZzZXQ9IjAiLz4KPHN0b3Agc3R5bGU9InN0b3AtY29sb3I6IzAwNjRlMSIgb2Zmc2V0PSIwLjQiLz4KPHN0b3Agc3R5bGU9InN0b3AtY29sb3I6IzAwNzNlZSIgb2Zmc2V0PSIwLjgzIi8+CjxzdG9wIHN0eWxlPSJzdG9wLWNvbG9yOiMwMDgyZmIiIG9mZnNldD0iMSIvPgo8L2xpbmVhckdyYWRpZW50Pgo8bGluZWFyR3JhZGllbnQgaWQ9IkdyYWRfTG9nbzIiIHgxPSI0NSIgeTE9IjEzOSIgeDI9IjQ1IiB5Mj0iNjYiIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIj4KPHN0b3Agc3R5bGU9InN0b3AtY29sb3I6IzAwODJmYiIgb2Zmc2V0PSIwIi8+CjxzdG9wIHN0eWxlPSJzdG9wLWNvbG9yOiMwMDY0ZTAiIG9mZnNldD0iMSIvPgo8L2xpbmVhckdyYWRpZW50Pgo8L2RlZnM+CjxwYXRoIGlkPSJMb2dvMCIgc3R5bGU9ImZpbGw6IzAwODFmYiIgZD0ibTMxLjA2LDEyNS45NmMwLDEwLjk4IDIuNDEsMTkuNDEgNS41NiwyNC41MSA0LjEzLDYuNjggMTAuMjksOS41MSAxNi41Nyw5LjUxIDguMSwwIDE1LjUxLTIuMDEgMjkuNzktMjEuNzYgMTEuNDQtMTUuODMgMjQuOTItMzguMDUgMzMuOTktNTEuOThsMTUuMzYtMjMuNmMxMC42Ny0xNi4zOSAyMy4wMi0zNC42MSAzNy4xOC00Ni45NiAxMS41Ni0xMC4wOCAyNC4wMy0xNS42OCAzNi41OC0xNS42OCAyMS4wNywwIDQxLjE0LDEyLjIxIDU2LjUsMzUuMTEgMTYuODEsMjUuMDggMjQuOTcsNTYuNjcgMjQuOTcsODkuMjcgMCwxOS4zOC0zLjgyLDMzLjYyLTEwLjMyLDQ0Ljg3LTYuMjgsMTAuODgtMTguNTIsMjEuNzUtMzkuMTEsMjEuNzVsMC0zMS4wMmMxNy42MywwIDIyLjAzLTE2LjIgMjIuMDMtMzQuNzQgMC0yNi40Mi02LjE2LTU1Ljc0LTE5LjczLTc2LjY5LTkuNjMtMTQuODYtMjIuMTEtMjMuOTQtMzUuODQtMjMuOTQtMTQuODUsMC0yNi44LDExLjItNDAuMjMsMzEuMTctNy4xNCwxMC42MS0xNC40NywyMy41NC0yMi43LDM4LjEzbC05LjA2LDE2LjA1Yy0xOC4yLDMyLjI3LTIyLjgxLDM5LjYyLTMxLjkxLDUxLjc1LTE1Ljk1LDIxLjI0LTI5LjU3LDI5LjI5LTQ3LjUsMjkuMjktMjEuMjcsMC0zNC43Mi05LjIxLTQzLjA1LTIzLjA5LTYuOC0xMS4zMS0xMC4xNC0yNi4xNS0xMC4xNC00My4wNnoiLz4KPHBhdGggaWQ9IkxvZ28xIiBzdHlsZT0iZmlsbDp1cmwoI0dyYWRfTG9nbzEpIiBkPSJtMjQuNDksMzcuM2MxNC4yNC0yMS45NSAzNC43OS0zNy4zIDU4LjM2LTM3LjMgMTMuNjUsMCAyNy4yMiw0LjA0IDQxLjM5LDE1LjYxIDE1LjUsMTIuNjUgMzIuMDIsMzMuNDggNTIuNjMsNjcuODFsNy4zOSwxMi4zMmMxNy44NCwyOS43MiAyNy45OSw0NS4wMSAzMy45Myw1Mi4yMiA3LjY0LDkuMjYgMTIuOTksMTIuMDIgMTkuOTQsMTIuMDIgMTcuNjMsMCAyMi4wMy0xNi4yIDIyLjAzLTM0Ljc0bDI3LjQtLjg2YzAsMTkuMzgtMy44MiwzMy42Mi0xMC4zMiw0NC44Ny02LjI4LDEwLjg4LTE4LjUyLDIxLjc1LTM5LjExLDIxLjc1LTEyLjgsMC0yNC4xNC0yLjc4LTM2LjY4LTE0LjYxLTkuNjQtOS4wOC0yMC45MS0yNS4yMS0yOS41OC0zOS43MWwtMjUuNzktNDMuMDhjLTEyLjk0LTIxLjYyLTI0LjgxLTM3Ljc0LTMxLjY4LTQ1LjA0LTcuMzktNy44NS0xNi44OS0xNy4zMy0zMi4wNS0xNy4zMy0xMi4yNywwLTIyLjY5LDguNjEtMzEuNDEsMjEuNzh6Ii8+CjxwYXRoIGlkPSJMb2dvMiIgc3R5bGU9ImZpbGw6dXJsKCNHcmFkX0xvZ28yKSIgZD0ibTgyLjM1LDMxLjIzYy0xMi4yNywwLTIyLjY5LDguNjEtMzEuNDEsMjEuNzgtMTIuMzMsMTguNjEtMTkuODgsNDYuMzMtMTkuODgsNzIuOTUgMCwxMC45OCAyLjQxLDE5LjQxIDUuNTYsMjQuNTFsLTI2LjQ4LDE3LjQ0Yy02LjgtMTEuMzEtMTAuMTQtMjYuMTUtMTAuMTQtNDMuMDYgMC0zMC43NSA4LjQ0LTYyLjggMjQuNDktODcuNTUgMTQuMjQtMjEuOTUgMzQuNzktMzcuMyA1OC4zNi0zNy4zeiIvPgo8L3N2Zz4K"
)
_BING_SVG_B64 = (
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHhtbDpzcGFjZT0icHJlc2VydmUiIGZpbGw9Im5vbmUiIHZpZXdCb3g9IjAgMCA2NzggMTAyNCI+PHBhdGggZmlsbD0idXJsKCNhKSIgZD0iTTAgNzc4LjNjMTQuNiAxMjMuOCAyMjMuOCAxNDMgMjM2LjggNzkuOS0uMy0uNC0uNS02NzguMS0uNS02NzguMS0zLjYtNDYtMjYuMi03Mi02MS42LTk2LjUtMzMtMjIuNy03NC40LTUwLjQtOTYuOS02Ni40QzE0LjItMjggLjEgMzEuNCAwIDMzLjJjMCAwIC4zIDc0Ni40IDAgNzQ1LjF6Ii8+PHBhdGggZmlsbD0idXJsKCNiKSIgZD0iTTIzNi44IDgzMi44Yy05Ni4yIDcyLjUtMjE3IDQyLjctMjM0LjQtNDQtLjgtNC4yLTIuNC0xMC40LTIuNC0xMC40cy45IDguNSAyIDE2LjZjMS4yIDguNSAzLjcgMjAuOCA2LjMgMzEuMyAzMCAxMTcuOCAxMzIuMSAxODYgMjMwLjQgMTk2LjZDMzczLjMgMTAzNC44IDQ5Ny40IDkzMSA1OTkgODU1LjhjNi4zLTYuMiAxNS40LTE2LjIgMTguMS0yMC4xIDY2LjItOTUtMTMuNi0xOTctNzIuNS0xOTNhNTkxNTQgNTkxNTQgMCAwIDAtMzA3LjcgMTkwLjFaIi8+PHBhdGggZmlsbD0idXJsKCNjKSIgZmlsbC1ydWxlPSJldmVub2RkIiBkPSJNMzEyLjggMzgxYzcuNCA0NyAzNC42IDEwOC43IDU5LjYgMTcyLjYgMjAuMiA0MS4zIDYyIDUzLjQgMTAzIDY1LjUgNDIuNCAxMi42IDY1LjYgMjEgODUuNiAzMC45IDEzOC41IDY4LjcgMzguNSAyMDcuNyA1OS42IDE4MS40IDg5LTExMC43IDc5LjctMzI1LjQtOTAtNDE4LjEtNTcuNi0yOC43LTExNS40LTY2LjYtMTU2LjUtODMuNi00MS0xNy02OC43IDQuMy02MS4zIDUxLjN6IiBjbGlwLXJ1bGU9ImV2ZW5vZGQiLz48ZGVmcz48cmFkaWFsR3JhZGllbnQgaWQ9ImMiIGN4PSIwIiBjeT0iMCIgcj0iMSIgZ3JhZGllbnRUcmFuc2Zvcm09Im1hdHJpeCgtMzQ3IC0zOTkuMyAyODcuMyAtMjQ5LjggNjU1IDcyMikiIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIj48c3RvcCBzdG9wLWNvbG9yPSIjMDBDQUNDIi8+PHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjMDQ4RkNFIi8+PC9yYWRpYWxHcmFkaWVudD48cmFkaWFsR3JhZGllbnQgaWQ9ImIiIGN4PSIwIiBjeT0iMCIgcj0iMSIgZ3JhZGllbnRUcmFuc2Zvcm09Im1hdHJpeCg1MjYgLTIyNS40IDM3NS42IDg3Ni42IDg4LjggOTE1LjEpIiBncmFkaWVudFVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHN0b3Agc3RvcC1jb2xvcj0iIzAwQkJFQyIvPjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iIzI3NTZBOSIvPjwvcmFkaWFsR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJhIiB4MT0iMTE4LjQiIHgyPSIxMTguNCIgeTE9IjAiIHkyPSI4ODQuNCIgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiPjxzdG9wIHN0b3AtY29sb3I9IiMwMEJCRUMiLz48c3RvcCBvZmZzZXQ9IjEiIHN0b3AtY29sb3I9IiMyNzU2QTkiLz48L2xpbmVhckdyYWRpZW50PjwvZGVmcz48L3N2Zz4="
)
def _logo_img(b64: str, alt: str) -> str:
    return f"<img class='channel-logo' src='data:image/svg+xml;base64,{b64}' alt='{alt}'/>"

# Channel-icon visuals — real brand SVGs for Google/Meta/Bing; emoji for the rest.
CHANNEL_GLYPHS = {
    "google_ads":     ("Google Ads",       _logo_img(_GOOGLE_G_SVG_B64, "Google")),
    "meta_ads":       ("Meta Ads",         _logo_img(_META_SVG_B64, "Meta")),
    "bing_ads":       ("Bing Ads",         _logo_img(_BING_SVG_B64, "Bing")),
    "google_organic": ("Google Organic",   "<span class='glyph glyph-organic'>🔍</span>"),
    "direct_other":   ("Direct/Other Traffic", "<span class='glyph glyph-direct'>🚦</span>"),
}


def render_channel_sprint_single(channel: dict[str, Any], out_path: Path | str) -> Path:
    """Render a single Channel Sprint sub-table (one channel) as its own image.

    channel dict: {
      key: "google_ads" | "meta_ads" | "bing_ads" | "google_organic" | "direct_other",
      rows: [{card_code, cpa, goal, mtd, pacing, pct, pct_value}, ...],
      totals: {goal, mtd, pacing, pct, pct_value}
    }
    """
    key = channel["key"]
    label, glyph = CHANNEL_GLYPHS.get(key, (key, ""))
    rows = channel["rows"]
    totals = channel.get("totals")
    total_rows = 1 + len(rows) + (1 if totals else 0)  # header + data rows + totals

    icon_cell = (
        f"<td rowspan='{total_rows}' class='channel-icon'>"
        f"<div class='channel-label'>{label}</div>"
        f"<div class='channel-glyph'>{glyph}</div>"
        f"</td>"
    )

    header_row = (
        f"<tr class='channel-sprint-head'>{icon_cell}"
        f"<th>Card</th><th>CPA</th>"
        f"<th class='blue-head'>Monthly Goal</th>"
        f"<th>Actuals MTD</th><th>Pacing</th>"
        f"<th>% Pacing to Goal</th></tr>"
    )

    body_html: list[str] = []
    for r in rows:
        body_html.append(
            "<tr>"
            f"<td class='label'>{CARD_NAMES_FULL.get(r['card_code'], r['card_code'])}</td>"
            f"<td class='num'>{r.get('cpa', '')}</td>"
            f"<td class='num blue-cell'>{r.get('goal', '')}</td>"
            f"<td class='num'>{r.get('mtd', '')}</td>"
            f"<td class='num'>{r.get('pacing', '')}</td>"
            + _gradient_cell(r.get("pct", "n/a"), r.get("pct_value"))
            + "</tr>"
        )
    if totals:
        body_html.append(
            "<tr class='totals-row'>"
            "<td class='label'>Totals</td>"
            "<td class='num'></td>"
            f"<td class='num blue-cell'>{totals.get('goal', '')}</td>"
            f"<td class='num'>{totals.get('mtd', '')}</td>"
            f"<td class='num'>{totals.get('pacing', '')}</td>"
            + _gradient_cell(totals.get("pct", "n/a"), totals.get("pct_value"))
            + "</tr>"
        )

    table_html = f"<table class='card-sprint channel-sprint'>{header_row}{''.join(body_html)}</table>"
    return render_html_to_png(_wrap(table_html, body_class="compact"), out_path, viewport_width=1200)


def render_bottom_roas_summary(channels: list[dict[str, Any]], out_path: Path | str) -> Path:
    """Render Mary's bottom-of-page ROAS summary — 3 stacked blocks.

    channels = [{"name": "Google", "roas": "110%", "profit_loss": "$13,057",
                 "spend": "$132,836"}, ...]
    """
    blocks: list[str] = []
    for ch in channels:
        blocks.append(
            "<table class='bottom-roas'>"
            "<tr>"
            f"<th class='blue-head'>{ch['name']} ROAS<br>(MTD)</th>"
            "<th>Profit/Loss<br>(MTD)</th>"
            "<th>Spend</th>"
            "</tr>"
            "<tr>"
            f"<td class='num bold green-bg'>{ch['roas']}</td>"
            f"<td class='num bold green-bg'>{ch['profit_loss']}</td>"
            f"<td class='num bold'>{ch['spend']}</td>"
            "</tr>"
            "</table>"
            "<div style='height:18px;'></div>"
        )
    # Trim trailing spacer for tight crop
    if blocks:
        blocks[-1] = blocks[-1].replace("<div style='height:18px;'></div>", "")
    return render_html_to_png(_wrap("\n".join(blocks), body_class="compact"), out_path, viewport_width=480)


def render_mini_pacing_table(
    channel_name: str,
    rows: list[dict[str, Any]],
    out_path: Path | str,
) -> Path:
    """Render the small "Pacing — Google/Bing/Meta" table inside NEXT STEPS.

    rows = [{"card_code": "ABP", "last": "71%", "last_value": 71.0,
             "ud": "DN", "ud_color": "red_bg",
             "current": "61%", "current_value": 61.0}, ...]
    """
    header = (
        "<tr class='mini-head'>"
        f"<th class='mini-channel'>{channel_name}</th>"
        "<th>Last</th><th>^v</th><th>Current</th>"
        "</tr>"
    )
    body_html: list[str] = []
    for r in rows:
        ud_cc = _color_class(r.get("ud_color"))
        body_html.append(
            "<tr>"
            f"<td class='label'>{r['card_code']}</td>"
            + _gradient_cell(r.get("last", "n/a"), r.get("last_value"))
            + f"<td class='num bold {ud_cc}'>{r.get('ud', 'n/a')}</td>"
            + _gradient_cell(r.get("current", "n/a"), r.get("current_value"))
            + "</tr>"
        )
    table_html = (
        "<div class='mini-label'>Pacing</div>"
        f"<table class='mini-pacing'>{header}{''.join(body_html)}</table>"
    )
    return render_html_to_png(_wrap(table_html, body_class="compact"), out_path, viewport_width=900)


def render_channel_sprint(channels: list[dict[str, Any]], out_dir: Path | str) -> list[Path]:
    """Render each of the 5 channels as its own image.

    Returns a list of output paths in the same order as `channels`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ch in channels:
        paths.append(render_channel_sprint_single(ch, out_dir / f"channel_{ch['key']}.png"))
    return paths


# === Smoke test =============================================================

if __name__ == "__main__":
    out = Path("/tmp/renderer_test")
    out.mkdir(exist_ok=True)

    # Test pacing tables (mirrors Mary's actual May 13 sample with full row coloring)
    cards_data = [
        {
            "card_code": "ABP", "card_color": "green",
            "rows": [
                {"label": "EOM Pacing",
                 "last": "225",   "last_color": "green_bg",
                 "ud":   "DN",    "ud_color":   "red_bg",
                 "current": "210", "current_color": "green_bg",
                 "current_per_day": "6", "needed_per_day": "n/a"},
                {"label": "Pacing to Min",
                 "last": "225%",  "last_color": "green_bg",
                 "ud":   "DN",    "ud_color":   "red_bg",
                 "current": "210%", "current_color": "green_bg",
                 "current_per_day": "6", "needed_per_day": "0",
                 "needed_per_day_color": "green_bg"},
                {"label": "Pacing to Stretch",
                 "last": "141%",  "last_color": "green_bg",
                 "ud":   "DN",    "ud_color":   "red_bg",
                 "current": "131%", "current_color": "green_bg",
                 "current_per_day": "6", "needed_per_day": "4",
                 "needed_per_day_color": "green_bg"},
            ],
        },
        {
            "card_code": "ABG", "card_color": "red",
            "rows": [
                {"label": "EOM Pacing",
                 "last": "65",    "last_color": "red_bg",
                 "ud":   "same",  "ud_color":   "yellow_bg",
                 "current": "65", "current_color": "red_bg",
                 "current_per_day": "2", "needed_per_day": "n/a"},
                {"label": "Pacing to Min",
                 "last": "65%",   "last_color": "red_bg",
                 "ud":   "same",  "ud_color":   "yellow_bg",
                 "current": "65%", "current_color": "red_bg",
                 "current_per_day": "2", "needed_per_day": "5",
                 "needed_per_day_color": "red_bg"},
                {"label": "Pacing to Stretch",
                 "last": "41%",   "last_color": "red_bg",
                 "ud":   "same",  "ud_color":   "yellow_bg",
                 "current": "41%", "current_color": "red_bg",
                 "current_per_day": "2", "needed_per_day": "10",
                 "needed_per_day_color": "red_bg"},
            ],
        },
    ]
    p = render_pacing_tables(cards_data, out / "pacing_01_abp_abg.png", period_label="May")
    print(f"Pacing 01: {p} ({p.stat().st_size:,} bytes)")

    # Pacing image 02 — AP + AP Tiers (4-tier card with notes)
    ap_card = {
        "card_code": "AP", "card_color": "green",
        "rows": [
            {"label": "EOM Pacing",
             "last": "405",  "last_color": "green_bg",
             "ud":   "n/a",  "ud_color":   "gray_bg",
             "current": "428", "current_color": "green_bg",
             "current_per_day": "12", "needed_per_day": "n/a"},
            {"label": "Pacing to Min",
             "last": "116%", "last_color": "green_bg",
             "ud":   "n/a",  "ud_color":   "gray_bg",
             "current": "122%", "current_color": "green_bg",
             "current_per_day": "12", "needed_per_day": "10",
             "needed_per_day_color": "green_bg"},
            {"label": "Pacing to Stretch",
             "last": "81%",  "last_color": "red_bg",
             "ud":   "n/a",  "ud_color":   "gray_bg",
             "current": "86%", "current_color": "yellow_bg",
             "current_per_day": "12", "needed_per_day": "22",
             "needed_per_day_color": "red_bg"},
        ],
        "tiers": {
            "header_label": "AP Tiers",
            "dot_color": "yellow",
            "notes": "*Goals edited: Min 350+ Stretch 500+",
            "notes_bg": "green_bg",
            "actuals": 219, "pacing": 428,
            "status": "Low Mid Achieved, Pacing to Top Mid",
            "status_bg": "yellow_bg",
            "breakpoints": [
                ("Bottom Tier",    "0-149",   "red_bg"),
                ("Low Mid Tier.",  "150-349", "orange_bg"),
                ("Top Mid Tier.",  "350+",    "yellow_bg"),
                ("Tiipy Top Tier.","500+",    "green_bg"),
            ],
        },
    }
    p = render_pacing_tables([ap_card], out / "pacing_02_ap.png", period_label="May", include_title=False)
    print(f"Pacing 02: {p} ({p.stat().st_size:,} bytes)")

    # Pacing image 03 — AG + AG Tiers (3-tier) + BCP + BCP Tiers (2-tier)
    ag_card = {
        "card_code": "AG", "card_color": "green",
        "rows": [
            {"label": "EOM Pacing",
             "last": "673",  "last_color": "green_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "713", "current_color": "green_bg",
             "current_per_day": "21", "needed_per_day": "n/a"},
            {"label": "Pacing to Min",
             "last": "168%", "last_color": "green_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "178%", "current_color": "green_bg",
             "current_per_day": "21", "needed_per_day": "2",
             "needed_per_day_color": "green_bg"},
            {"label": "Pacing to Stretch",
             "last": "122%", "last_color": "green_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "130%", "current_color": "green_bg",
             "current_per_day": "21", "needed_per_day": "14",
             "needed_per_day_color": "green_bg"},
        ],
        "tiers": {
            "header_label": "AG Tiers", "dot_color": "green",
            "actuals": 370, "pacing": 713,
            "status": "Top Tier Achived!", "status_bg": "green_bg",
            "breakpoints": [
                ("Bottom Tier", "0-149",   "red_bg"),
                ("Middle Tier", "150-349", "orange_bg"),
                ("Top Tier.",   "350+",    "green_bg"),
            ],
        },
    }
    bcp_card = {
        "card_code": "BCP", "card_color": "red",
        "rows": [
            {"label": "EOM Pacing",
             "last": "112",  "last_color": "green_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "116", "current_color": "green_bg",
             "current_per_day": "3", "needed_per_day": "n/a"},
            {"label": "Pacing to Stretch",
             "last": "56%",  "last_color": "red_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "58%", "current_color": "red_bg",
             "current_per_day": "3", "needed_per_day": "11",
             "needed_per_day_color": "red_bg"},
        ],
        "tiers": {
            "header_label": "BCP Tiers", "dot_color": "red",
            "actuals": 55, "pacing": 116,
            "status": "Pacing in Bottom Tier", "status_bg": "red_bg",
            "breakpoints": [
                ("Bottom Tier", "0-199", "red_bg"),
                ("Top Tier.",   "200+",  "green_bg"),
            ],
        },
    }
    p = render_pacing_tables([ag_card, bcp_card], out / "pacing_03_ag_bcp.png", period_label="May", include_title=False)
    print(f"Pacing 03: {p} ({p.stat().st_size:,} bytes)")

    # Pacing image 04 — BCE alone
    bce_card = {
        "card_code": "BCE", "card_color": "yellow",
        "rows": [
            {"label": "EOM Pacing",
             "last": "212",  "last_color": "red_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "218", "current_color": "red_bg",
             "current_per_day": "6", "needed_per_day": "n/a"},
            {"label": "Pacing to Min",
             "last": "85%",  "last_color": "yellow_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "87%", "current_color": "yellow_bg",
             "current_per_day": "6", "needed_per_day": "11",
             "needed_per_day_color": "red_bg"},
            {"label": "Pacing to Stretch",
             "last": "61%",  "last_color": "red_bg",
             "ud":   "UP",   "ud_color":   "green_bg",
             "current": "62%", "current_color": "red_bg",
             "current_per_day": "6", "needed_per_day": "19",
             "needed_per_day_color": "red_bg"},
        ],
    }
    p = render_pacing_tables([bce_card], out / "pacing_04_bce.png", period_label="May", include_title=False)
    print(f"Pacing 04: {p} ({p.stat().st_size:,} bytes)")

    # Test ROAS (May 18 sample — Google/Meta up, Bing ROAS down)
    roas_data = [
        {"name": "Google", "color": "green", "rows": [
            {"metric": "ROAS",        "last": "106%",     "last_color": "green_bg",
             "ud": "UP",   "ud_color": "green_bg",
             "current": "110%",       "current_color": "green_bg"},
            {"metric": "Profit/Loss", "last": "$6,816",   "last_color": "green_bg",
             "ud": "UP",   "ud_color": "green_bg",
             "current": "$13,057",    "current_color": "green_bg"},
            {"metric": "Spend",       "last": "$106,975", "last_color": "gray_bg",
             "ud": "n/a",  "ud_color": "gray_bg",
             "current": "$132,836",   "current_color": "gray_bg"},
        ]},
        {"name": "Meta", "color": "green", "rows": [
            {"metric": "ROAS",        "last": "112%",     "last_color": "green_bg",
             "ud": "UP",   "ud_color": "green_bg",
             "current": "120%",       "current_color": "green_bg"},
            {"metric": "Profit/Loss", "last": "$42,580",  "last_color": "green_bg",
             "ud": "UP",   "ud_color": "green_bg",
             "current": "$82,037",    "current_color": "green_bg"},
            {"metric": "Spend",       "last": "$354,395", "last_color": "gray_bg",
             "ud": "n/a",  "ud_color": "gray_bg",
             "current": "$418,088",   "current_color": "gray_bg"},
        ]},
        {"name": "Bing", "color": "green", "rows": [
            {"metric": "ROAS",        "last": "226%",     "last_color": "green_bg",
             "ud": "DN",   "ud_color": "red_bg",
             "current": "187%",       "current_color": "green_bg"},
            {"metric": "Profit/Loss", "last": "$4,536",   "last_color": "green_bg",
             "ud": "UP",   "ud_color": "green_bg",
             "current": "$4,562",     "current_color": "green_bg"},
            {"metric": "Spend",       "last": "$3,589",   "last_color": "gray_bg",
             "ud": "n/a",  "ud_color": "gray_bg",
             "current": "$5,263",     "current_color": "gray_bg"},
        ]},
    ]
    p = render_roas_section(roas_data, out / "roas.png")
    print(f"ROAS: {p} ({p.stat().st_size:,} bytes)")

    # Test card sprint (Mary's May 18 actual numbers)
    card_sprint = [
        {"card_code": "ABP", "month": "May", "cpa": "$1,200",
         "min": 100, "tier": "n/a", "stretch": 160, "mtd": 105, "pacing": 210,
         "pct_min": "210%", "pct_min_value": 210.0,
         "pct_stretch": "131%", "pct_stretch_value": 131.0},
        {"card_code": "ABG", "month": "May", "cpa": "$1,000",
         "min": 100, "tier": "n/a", "stretch": 160, "mtd": 30, "pacing": 65,
         "pct_min": "65%", "pct_min_value": 65.0,
         "pct_stretch": "41%", "pct_stretch_value": 41.0},
        {"card_code": "AP", "month": "May", "cpa": "$600-$1250",
         "min": 350, "tier": 350, "stretch": 500, "mtd": 219, "pacing": 428,
         "pct_min": "122%", "pct_min_value": 122.0,
         "pct_stretch": "86%", "pct_stretch_value": 86.0},
        {"card_code": "AG", "month": "May", "cpa": "$600-$1100",
         "min": 400, "tier": 350, "stretch": 550, "mtd": 370, "pacing": 713,
         "pct_min": "178%", "pct_min_value": 178.0,
         "pct_stretch": "130%", "pct_stretch_value": 130.0},
        {"card_code": "BCP", "month": "May", "cpa": "$350-$450",
         "min": "n/a", "tier": "n/a", "stretch": 200, "mtd": 55, "pacing": 116,
         "pct_min": "n/a", "pct_min_value": None,
         "pct_stretch": "58%", "pct_stretch_value": 58.0},
        {"card_code": "BCE", "month": "May", "cpa": "$300",
         "min": 250, "tier": "n/a", "stretch": 350, "mtd": 109, "pacing": 218,
         "pct_min": "87%", "pct_min_value": 87.0,
         "pct_stretch": "62%", "pct_stretch_value": 62.0},
        {"card_code": "Totals", "min": 950, "tier": "n/a", "stretch": 1970,
         "mtd": 888, "pacing": 1750,
         "pct_min": "", "pct_min_value": None,
         "pct_stretch": "89%", "pct_stretch_value": 89.0},
    ]
    p = render_card_sprint_summary(card_sprint, out / "card_sprint.png", month="May")
    print(f"Card Sprint: {p} ({p.stat().st_size:,} bytes)")

    # Channel Sprint — Google Ads (Mary's May 18 actuals)
    channels = [
        {"key": "google_ads",
         "rows": [
             {"card_code": "ABP", "cpa": "$750-$1,500", "goal": 30,  "mtd": 8,  "pacing": 18,  "pct": "61%",  "pct_value": 61.0},
             {"card_code": "ABG", "cpa": "$1,000",     "goal": 30,  "mtd": 6,  "pacing": 9,   "pct": "30%",  "pct_value": 30.0},
             {"card_code": "AP",  "cpa": "$600-$1000", "goal": 112, "mtd": 33, "pacing": 60,  "pct": "53%",  "pct_value": 53.0},
             {"card_code": "AG",  "cpa": "$600-$1000", "goal": 41,  "mtd": 25, "pacing": 47,  "pct": "113%", "pct_value": 113.0},
             {"card_code": "BCP", "cpa": "$250-$400",  "goal": 48,  "mtd": 11, "pacing": 25,  "pct": "52%",  "pct_value": 52.0},
             {"card_code": "BCE", "cpa": "$300",       "goal": 24,  "mtd": 5,  "pacing": 10,  "pct": "42%",  "pct_value": 42.0},
         ],
         "totals": {"goal": 84, "mtd": 88, "pacing": 168, "pct": "56%", "pct_value": 56.0}},
        {"key": "meta_ads",
         "rows": [
             {"card_code": "ABP", "cpa": "$750-$1,500", "goal": 73,  "mtd": 70,  "pacing": 139, "pct": "191%", "pct_value": 191.0},
             {"card_code": "ABG", "cpa": "$1,000",     "goal": 42,  "mtd": 14,  "pacing": 38,  "pct": "90%",  "pct_value": 90.0},
             {"card_code": "AP",  "cpa": "$600-$1000", "goal": 276, "mtd": 144, "pacing": 280, "pct": "102%", "pct_value": 102.0},
             {"card_code": "AG",  "cpa": "$600-$1000", "goal": 197, "mtd": 303, "pacing": 587, "pct": "298%", "pct_value": 298.0},
             {"card_code": "BCP", "cpa": "$250-$400",  "goal": 111, "mtd": 38,  "pacing": 76,  "pct": "68%",  "pct_value": 68.0},
             {"card_code": "BCE", "cpa": "$300",       "goal": 94,  "mtd": 103, "pacing": 205, "pct": "218%", "pct_value": 218.0},
         ],
         "totals": {"goal": 792, "mtd": 672, "pacing": 1329, "pct": "168%", "pct_value": 168.0}},
        {"key": "bing_ads",
         "rows": [
             {"card_code": "ABP", "cpa": "$750-$1,500", "goal": 4,  "mtd": 3, "pacing": 5,  "pct": "117%", "pct_value": 117.0},
             {"card_code": "ABG", "cpa": "$1,000",     "goal": 6,  "mtd": 4, "pacing": 7,  "pct": "115%", "pct_value": 115.0},
             {"card_code": "AP",  "cpa": "$600-$1000", "goal": 16, "mtd": 4, "pacing": 7,  "pct": "43%",  "pct_value": 43.0},
             {"card_code": "AG",  "cpa": "$600-$1000", "goal": 4,  "mtd": 0, "pacing": 0,  "pct": "0%",   "pct_value": 0.0},
             {"card_code": "BCP", "cpa": "$250-$400",  "goal": 5,  "mtd": 0, "pacing": 0,  "pct": "0%",   "pct_value": 0.0},
             {"card_code": "BCE", "cpa": "$300",       "goal": 3,  "mtd": 0, "pacing": 0,  "pct": "0%",   "pct_value": 0.0},
         ],
         "totals": {"goal": 38, "mtd": 11, "pacing": 19, "pct": "49%", "pct_value": 49.0}},
        {"key": "google_organic",
         "rows": [
             {"card_code": "ABP", "cpa": "$750-$1,500", "goal": 53,  "mtd": 13, "pacing": 28, "pct": "53%",  "pct_value": 53.0},
             {"card_code": "ABG", "cpa": "$1,000",     "goal": 19,  "mtd": 7,  "pacing": 13, "pct": "68%",  "pct_value": 68.0},
             {"card_code": "AP",  "cpa": "$600-$1000", "goal": 89,  "mtd": 15, "pacing": 32, "pct": "36%",  "pct_value": 36.0},
             {"card_code": "AG",  "cpa": "$600-$1000", "goal": 40,  "mtd": 23, "pacing": 44, "pct": "109%", "pct_value": 109.0},
             {"card_code": "BCP", "cpa": "$250-$400",  "goal": 9,   "mtd": 2,  "pacing": 4,  "pct": "43%",  "pct_value": 43.0},
             {"card_code": "BCE", "cpa": "$300",       "goal": 3,   "mtd": 0,  "pacing": 0,  "pct": "0%",   "pct_value": 0.0},
         ],
         "totals": {"goal": 213, "mtd": 60, "pacing": 121, "pct": "57%", "pct_value": 57.0}},
        {"key": "direct_other",
         "rows": [
             {"card_code": "ABP", "cpa": "$750-$1,500", "goal": 23,  "mtd": 9,   "pacing": 23,  "pct": "101%", "pct_value": 101.0},
             {"card_code": "ABG", "cpa": "$1,000",     "goal": 12,  "mtd": 4,   "pacing": 6,   "pct": "55%",  "pct_value": 55.0},
             {"card_code": "AP",  "cpa": "$600-$1000", "goal": 61,  "mtd": 22,  "pacing": 46,  "pct": "76%",  "pct_value": 76.0},
             {"card_code": "AG",  "cpa": "$600-$1000", "goal": 21,  "mtd": 19,  "pacing": 36,  "pct": "171%", "pct_value": 171.0},
             {"card_code": "BCP", "cpa": "$250-$400",  "goal": 7,   "mtd": 4,   "pacing": 9,   "pct": "131%", "pct_value": 131.0},
             {"card_code": "BCE", "cpa": "$300",       "goal": 4,   "mtd": 0,   "pacing": 0,   "pct": "0%",   "pct_value": 0.0},
         ],
         "totals": {"goal": 128, "mtd": 58, "pacing": 120, "pct": "94%", "pct_value": 94.0}},
    ]
    paths = render_channel_sprint(channels, out)
    for p in paths:
        print(f"Channel: {p} ({p.stat().st_size:,} bytes)")

    # Mini Pacing-Google table (NEXT STEPS bullet)
    mini_pacing = [
        {"card_code": "ABP", "last": "71%", "last_value": 71.0,
         "ud": "DN",   "ud_color": "red_bg",
         "current": "61%", "current_value": 61.0},
        {"card_code": "ABG", "last": "27%", "last_value": 27.0,
         "ud": "UP",   "ud_color": "green_bg",
         "current": "30%", "current_value": 30.0},
        {"card_code": "AP",  "last": "57%", "last_value": 57.0,
         "ud": "DN",   "ud_color": "red_bg",
         "current": "53%", "current_value": 53.0},
        {"card_code": "AG",  "last": "94%", "last_value": 94.0,
         "ud": "UP",   "ud_color": "green_bg",
         "current": "113%","current_value": 113.0},
        {"card_code": "BCP", "last": "52%", "last_value": 52.0,
         "ud": "same", "ud_color": "yellow_bg",
         "current": "52%", "current_value": 52.0},
        {"card_code": "BCE", "last": "0%",  "last_value": 0.0,
         "ud": "UP",   "ud_color": "green_bg",
         "current": "42%", "current_value": 42.0},
    ]
    p = render_mini_pacing_table("Google", mini_pacing, out / "mini_pacing_google.png")
    print(f"Mini Pacing: {p} ({p.stat().st_size:,} bytes)")

    # Bottom ROAS summary (3 stacked blocks)
    bottom_roas = [
        {"name": "Google", "roas": "110%", "profit_loss": "$13,057", "spend": "$132,836"},
        {"name": "Meta",   "roas": "120%", "profit_loss": "$82,037", "spend": "$418,088"},
        {"name": "Bing",   "roas": "187%", "profit_loss": "$4,562",  "spend": "$5,263"},
    ]
    p = render_bottom_roas_summary(bottom_roas, out / "bottom_roas.png")
    print(f"Bottom ROAS: {p} ({p.stat().st_size:,} bytes)")
