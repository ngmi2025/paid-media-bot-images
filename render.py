"""Paid Media Bot — Mary-format renderer.

Produces the 11 PNG images Mary uses in her weekly Tracking Report.
Each report renders:
  1. Pacing & Tier Tracking — header + ABP + ABG (paired)
  2. AP + AP Tiers
  3. AG + AG Tiers + BCP + BCP Tiers
  4. BCE (solo)
  5. ROAS mid-page (Google/Meta/Bing — Last|^v|Current rows for ROAS/P&L/Spend)
  6. NEXT STEPS Google helper (per-card Google pacing %)
  7. Card Sprint (10-col table)
  8. Channel Sprint 1 (Google Ads + Meta Ads)
  9. Channel Sprint 2 (Bing Ads)
 10. Channel Sprint 3 (Google Organic + Direct/Other Traffic)
 11. Bottom ROAS recap (compact 3-row Google/Meta/Bing)

Usage from CLI:
    python3 render.py <section> <input_json_path> <out_png_path>

Sections: pacing_1, pacing_2, pacing_3, pacing_4, roas_mid,
          ns_google, card_sprint, channel_sprint_1, channel_sprint_2,
          channel_sprint_3, roas_bottom

The input JSON shape per section is documented inline on each renderer.

Requires Playwright with Chromium. In the routine env, set:
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ----- Shared CSS (Mary's color palette + spreadsheet aesthetic) ----------

# Mary's actual palette, sampled from her real images:
#   green_strong  #B6E0B0   (green cells in Up Down column when UP)
#   green_med     #DDEDEA   (Notion-style green_bg, used by v3)
#   green_light   #E8F5E4
#   yellow_med    #FBF3DB   (Notion yellow_bg)
#   yellow_strong #F8E1A2
#   red_med       #E8B7B7   (red cell achievement)
#   red_light     #FBE4E4   (Notion red_bg)
#   red_strong    #D88080
#   gray_header   #F7F6F3   (section row backgrounds in Mary's images)
#   gray_neutral  #ECECE9   (n/a cells)
#   blue_header   #DCE9F2   (cyan-ish headers in card sprint blue boxes)

CSS = """
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 20px; background: white;
         font-family: -apple-system, 'Segoe UI', Arial, sans-serif;
         color: #1f1f1f; }
  .frame-header { display: inline-block; padding: 10px 16px;
                  border: 2px solid #1f1f1f; font-weight: 700;
                  font-size: 20px; margin-bottom: 14px; }
  .pacing-block, .roas-block, .helper-block, .channel-block, .roas-bottom {
                  margin-bottom: 18px; }
  table { border-collapse: collapse; width: 100%; }
  table.bordered td, table.bordered th { border: 1.5px solid #1f1f1f; }
  td, th { padding: 9px 12px; text-align: center; font-size: 14px;
           font-weight: 600; }
  th.label-col, td.label-col { text-align: left; }
  .green   { background: #C8E6C0; }
  .green-l { background: #DDEDEA; }
  .yellow  { background: #FBF3DB; }
  .yellow-s{ background: #F8E1A2; }
  .red     { background: #E8B7B7; }
  .red-l   { background: #FBE4E4; }
  .red-s   { background: #D88080; color: white; }
  .gray    { background: #ECECE9; color: #555; }
  .gray-h  { background: #F2F2F0; }
  .blue-h  { background: #DCE9F2; }
  .num     { font-variant-numeric: tabular-nums; }
  .small   { font-size: 12px; }
  .tier-row td { font-size: 11px; padding: 6px 8px; color: #5b5b5b; }
  .tier-label { font-weight: 700; font-size: 12px; }
  .annotation { font-weight: 700; font-size: 13px; }
  .logo-cell { width: 110px; text-align: center; padding: 8px; }
  .logo-cell img { max-width: 80px; max-height: 40px; }
  .totals-row { background: #F0F0EE; font-weight: 700; }
</style>
"""

# ----- Color helpers ------------------------------------------------------

def pct_color(pct: float | None, *, lo: float = 85, hi: float = 100) -> str:
    """Map a % to color class: <lo red, lo..hi yellow, >=hi green."""
    if pct is None:
        return "gray"
    if pct < lo:
        return "red"
    if pct < hi:
        return "yellow"
    return "green"

def dir_color(direction: str) -> str:
    """Direction string ('UP','DN','same','n/a') -> color class."""
    d = (direction or "").strip().lower()
    if d == "up":
        return "green"
    if d in ("dn", "down"):
        return "red"
    if d == "same":
        return "yellow"
    return "gray"

def dir_label(last: float | None, current: float | None) -> str:
    if last is None or current is None:
        return "n/a"
    if abs(last - current) < 0.5:
        return "same"
    return "UP" if current > last else "DN"

def fmt_int(n) -> str:
    if n is None:
        return "n/a"
    return f"{int(round(n)):,}"

def fmt_pct(p) -> str:
    if p is None:
        return "n/a"
    return f"{p:.0f}%"

def fmt_money(n) -> str:
    if n is None:
        return "n/a"
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(int(round(n))):,}"

# ----- HTML→PNG plumbing -------------------------------------------------

def render_html_to_png(html: str, out_path: Path | str, *,
                       viewport_width: int = 1100,
                       device_scale_factor: int = 2) -> Path:
    """Render an HTML string to PNG via Playwright (Chromium headless)."""
    from playwright.sync_api import sync_playwright
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    launch_args: dict[str, Any] = {"args": ["--no-sandbox"]}
    if exe:
        launch_args["executable_path"] = exe

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_args)
        ctx = browser.new_context(
            viewport={"width": viewport_width, "height": 800},
            device_scale_factor=device_scale_factor,
        )
        page = ctx.new_page()
        page.set_content(CSS + html)
        # Take a screenshot of just the rendered body
        body = page.locator("body")
        body.screenshot(path=str(out_path), omit_background=False)
        browser.close()
    return out_path


# ----- Per-card pacing block ---------------------------------------------

def _pacing_block_html(card_code: str, card_data: dict,
                       month_name: str, *, status: str = "green") -> str:
    """One card's pacing block (3 rows: EOM Pacing / Pacing to Min / Pacing to Stretch).

    card_data shape:
        {
          "last":    {"eom": 225, "pct_min": 225, "pct_stretch": 141},
          "current": {"eom": 210, "pct_min": 210, "pct_stretch": 131,
                       "current_per_day": 6,
                       "needed_per_day_min": 0,
                       "needed_per_day_stretch": 4},
          "has_min": True   # False for BCP
        }
    """
    last = card_data["last"]
    cur = card_data["current"]
    has_min = card_data.get("has_min", True)

    dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[status]

    # Row 1: EOM Pacing — Last vs Current
    eom_dir = dir_label(last["eom"], cur["eom"])
    last_eom_class = pct_color(last.get("pct_min"))
    cur_eom_class = pct_color(cur.get("pct_min"))

    # Row 2: Pacing to Min
    min_dir = dir_label(last.get("pct_min"), cur.get("pct_min")) if has_min else "n/a"
    last_min_class = pct_color(last.get("pct_min")) if has_min else "gray"
    cur_min_class = pct_color(cur.get("pct_min")) if has_min else "gray"

    # Row 3: Pacing to Stretch
    str_dir = dir_label(last.get("pct_stretch"), cur.get("pct_stretch"))
    last_str_class = pct_color(last.get("pct_stretch"))
    cur_str_class = pct_color(cur.get("pct_stretch"))

    rows = []
    rows.append(f"""
      <tr>
        <td class="label-col"><strong>EOM Pacing</strong></td>
        <td class="{last_eom_class} num">{fmt_int(last["eom"])}</td>
        <td class="{dir_color(eom_dir)}"><strong>{eom_dir}</strong></td>
        <td class="{cur_eom_class} num"><strong>{fmt_int(cur["eom"])}</strong></td>
        <td class="gray num">{fmt_int(cur.get("current_per_day"))}</td>
        <td class="gray num">n/a</td>
      </tr>""")
    if has_min:
        rows.append(f"""
          <tr>
            <td class="label-col"><strong>Pacing to Min</strong></td>
            <td class="{last_min_class} num">{fmt_pct(last.get('pct_min'))}</td>
            <td class="{dir_color(min_dir)}"><strong>{min_dir}</strong></td>
            <td class="{cur_min_class} num"><strong>{fmt_pct(cur.get('pct_min'))}</strong></td>
            <td class="gray num">{fmt_int(cur.get("current_per_day"))}</td>
            <td class="{cur_min_class} num">{fmt_int(cur.get('needed_per_day_min'))}</td>
          </tr>""")
    rows.append(f"""
      <tr>
        <td class="label-col"><strong>Pacing to Stretch</strong></td>
        <td class="{last_str_class} num">{fmt_pct(last.get('pct_stretch'))}</td>
        <td class="{dir_color(str_dir)}"><strong>{str_dir}</strong></td>
        <td class="{cur_str_class} num"><strong>{fmt_pct(cur.get('pct_stretch'))}</strong></td>
        <td class="gray num">{fmt_int(cur.get("current_per_day"))}</td>
        <td class="{cur_str_class} num">{fmt_int(cur.get('needed_per_day_stretch'))}</td>
      </tr>""")

    header_class = {"green": "green-l", "yellow": "yellow", "red": "red-l"}[status]
    return f"""
    <table class="bordered pacing-block" style="margin-bottom:14px;">
      <tr>
        <td class="label-col {header_class}"><strong>{dot} {card_code}</strong></td>
        <th>Last</th>
        <th>Up ^v Down</th>
        <th>Current</th>
        <th>Current/Day</th>
        <th>Needed/Day in {month_name}</th>
      </tr>
      {''.join(rows)}
    </table>
    """


def _tier_block_html(card_code: str, tier_data: dict, status: str = "green") -> str:
    """Tier sub-table for AP/AG/BCP.

    tier_data shape:
        {
          "tiers": [
              {"label": "Bottom Tier",  "range": "0-149",  "class": "red-l"},
              {"label": "Low Mid Tier.","range": "150-349","class": "yellow"},
              {"label": "Top Mid Tier.","range": "350+",   "class": "yellow-s"},
              {"label": "Tiipy Top Tier.","range":"500+",  "class": "green-l"},
          ],
          "actuals": 219,
          "pacing":  428,
          "annotation": "Low Mid Achieved, Pacing to Top Mid",
          "annotation_class": "yellow-s",
          "goals_note": "*Goals edited: Min 350+ Stretch 500+"  # optional
        }
    """
    dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[status]
    tiers = tier_data["tiers"]
    ncols_for_tiers = len(tiers)

    tier_label_cells = ""
    for t in tiers:
        tier_label_cells += (f'<td class="tier-row {t["class"]}">'
                             f'<div class="tier-label">{t["label"]}</div>'
                             f'<div>{t["range"]}</div></td>')

    goals_note = tier_data.get("goals_note", "")
    annotation = tier_data["annotation"]
    annotation_cls = tier_data.get("annotation_class", "yellow-s")

    return f"""
    <table class="bordered" style="margin-bottom:14px;">
      <tr>
        <td class="label-col gray-h"><strong>{dot} {card_code} Tiers</strong></td>
        <th>Actuals</th>
        <th>Pacing</th>
        <td colspan="{max(1, ncols_for_tiers - 2)}" class="label-col gray-h small">
          {goals_note}
        </td>
      </tr>
      <tr>
        <td class="label-col"><strong>Totals</strong></td>
        <td class="yellow num"><strong>{fmt_int(tier_data['actuals'])}</strong></td>
        <td class="yellow num"><strong>{fmt_int(tier_data['pacing'])}</strong></td>
        <td colspan="{max(1, ncols_for_tiers - 2)}"
            class="{annotation_cls} annotation">{annotation}</td>
      </tr>
      <tr>{tier_label_cells}</tr>
    </table>
    """


# ----- Section renderers --------------------------------------------------

def render_pacing_1(payload: dict, out_path: Path) -> Path:
    """Image 1: 'Pacing & Tier Tracking' header + ABP + ABG."""
    html = (
        '<div class="frame-header">Pacing &amp; Tier Tracking</div>'
        + _pacing_block_html("ABP", payload["ABP"], payload["month"],
                             status=payload["ABP"].get("status", "green"))
        + _pacing_block_html("ABG", payload["ABG"], payload["month"],
                             status=payload["ABG"].get("status", "red"))
    )
    return render_html_to_png(html, out_path, viewport_width=1100)


def render_pacing_2(payload: dict, out_path: Path) -> Path:
    """Image 2: AP + AP Tiers."""
    html = (
        _pacing_block_html("AP", payload["AP"], payload["month"],
                           status=payload["AP"].get("status", "green"))
        + _tier_block_html("AP", payload["AP_tier"],
                           status=payload["AP_tier"].get("status", "yellow"))
    )
    return render_html_to_png(html, out_path, viewport_width=1100)


def render_pacing_3(payload: dict, out_path: Path) -> Path:
    """Image 3: AG + AG Tiers + BCP + BCP Tiers."""
    html = (
        _pacing_block_html("AG", payload["AG"], payload["month"],
                           status=payload["AG"].get("status", "green"))
        + _tier_block_html("AG", payload["AG_tier"],
                           status=payload["AG_tier"].get("status", "green"))
        + _pacing_block_html("BCP", payload["BCP"], payload["month"],
                             status=payload["BCP"].get("status", "red"))
        + _tier_block_html("BCP", payload["BCP_tier"],
                           status=payload["BCP_tier"].get("status", "red"))
    )
    return render_html_to_png(html, out_path, viewport_width=1100)


def render_pacing_4(payload: dict, out_path: Path) -> Path:
    """Image 4: BCE solo."""
    html = _pacing_block_html("BCE", payload["BCE"], payload["month"],
                              status=payload["BCE"].get("status", "yellow"))
    return render_html_to_png(html, out_path, viewport_width=1100)


def render_roas_mid(payload: dict, out_path: Path) -> Path:
    """Image 5: 'ROAS' header + Google + Meta + Bing stacked.

    payload shape:
        {
          "channels": [
            {"name": "Google", "status": "green",
             "roas":     {"last": 106, "current": 110, "dir": "UP"},
             "profit":   {"last": 6816, "current": 13057, "dir": "UP"},
             "spend":    {"last": 106975, "current": 132836}},
            ... Meta, Bing
          ]
        }
    """
    blocks = ['<div class="frame-header">ROAS</div>']
    for ch in payload["channels"]:
        dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[ch.get("status", "green")]
        roas_dir = ch["roas"].get("dir") or dir_label(ch["roas"]["last"], ch["roas"]["current"])
        profit_dir = ch["profit"].get("dir") or dir_label(ch["profit"]["last"], ch["profit"]["current"])
        c_roas = pct_color(ch["roas"]["current"])
        c_roas_last = pct_color(ch["roas"]["last"])
        blocks.append(f"""
        <table class="bordered roas-block">
          <tr>
            <td class="label-col {('green-l' if ch.get('status','green')=='green' else 'red-l')}">
              <strong>{dot} {ch['name']}</strong>
            </td>
            <th>Last</th>
            <th>^v</th>
            <th>Current</th>
          </tr>
          <tr>
            <td class="label-col"><strong>ROAS</strong></td>
            <td class="{c_roas_last} num">{fmt_pct(ch['roas']['last'])}</td>
            <td class="{dir_color(roas_dir)}"><strong>{roas_dir}</strong></td>
            <td class="{c_roas} num"><strong>{fmt_pct(ch['roas']['current'])}</strong></td>
          </tr>
          <tr>
            <td class="label-col"><strong>Profit/Loss</strong></td>
            <td class="green-l num">{fmt_money(ch['profit']['last'])}</td>
            <td class="{dir_color(profit_dir)}"><strong>{profit_dir}</strong></td>
            <td class="green-l num"><strong>{fmt_money(ch['profit']['current'])}</strong></td>
          </tr>
          <tr>
            <td class="label-col"><strong>Spend</strong></td>
            <td class="gray num">{fmt_money(ch['spend']['last'])}</td>
            <td class="gray">n/a</td>
            <td class="gray num">{fmt_money(ch['spend']['current'])}</td>
          </tr>
        </table>
        """)
    return render_html_to_png("".join(blocks), out_path, viewport_width=900)


def render_ns_google_helper(payload: dict, out_path: Path) -> Path:
    """Image 6: NEXT STEPS Google helper — per-card Google pacing %."""
    rows = []
    for c in payload["cards"]:
        last_cls = pct_color(c["last"])
        cur_cls = pct_color(c["current"])
        d = c.get("dir") or dir_label(c["last"], c["current"])
        rows.append(f"""
          <tr>
            <td class="label-col gray-h"><strong>{c['code']}</strong></td>
            <td class="{last_cls} num">{fmt_pct(c['last'])}</td>
            <td class="{dir_color(d)}"><strong>{d}</strong></td>
            <td class="{cur_cls} num"><strong>{fmt_pct(c['current'])}</strong></td>
          </tr>""")
    html = f"""
    <div style="font-weight:700; font-size:18px; margin-bottom:6px;">Pacing</div>
    <table class="bordered helper-block" style="max-width:520px;">
      <tr>
        <td class="label-col gray-h"><strong>Google</strong></td>
        <th>Last</th>
        <th>^v</th>
        <th>Current</th>
      </tr>
      {''.join(rows)}
    </table>
    """
    return render_html_to_png(html, out_path, viewport_width=620)


def render_card_sprint(payload: dict, out_path: Path) -> Path:
    """Image 7: 10-col Card Sprint table.

    payload['rows']: list of dicts with keys
        card_full_name, month, cpa, min_threshold, tier_target, stretch_goal,
        actuals_mtd, pacing, pct_min, pct_stretch
    payload['totals']: dict with min_threshold, stretch_goal, actuals_mtd, pacing, pct_stretch
    """
    rows = []
    for r in payload["rows"]:
        min_cls = pct_color(r["pct_min"]) if r["pct_min"] is not None else "gray"
        str_cls = pct_color(r["pct_stretch"]) if r["pct_stretch"] is not None else "gray"
        rows.append(f"""
        <tr>
          <td class="label-col">{r['card_full_name']}</td>
          <td>{r['month']}</td>
          <td class="num">{r['cpa']}</td>
          <td class="blue-h num">{fmt_int(r['min_threshold']) if r['min_threshold'] is not None else 'n/a'}</td>
          <td class="blue-h num">{fmt_int(r['tier_target']) if r['tier_target'] is not None else 'n/a'}</td>
          <td class="blue-h num">{fmt_int(r['stretch_goal'])}</td>
          <td class="num">{fmt_int(r['actuals_mtd'])}</td>
          <td class="num">{fmt_int(r['pacing'])}</td>
          <td class="{min_cls} num"><strong>{fmt_pct(r['pct_min']) if r['pct_min'] is not None else 'n/a'}</strong></td>
          <td class="{str_cls} num"><strong>{fmt_pct(r['pct_stretch'])}</strong></td>
        </tr>""")
    t = payload["totals"]
    tot_cls = pct_color(t.get("pct_stretch"))
    rows.append(f"""
      <tr class="totals-row">
        <td class="label-col"><strong>Totals</strong></td>
        <td></td><td></td>
        <td class="blue-h num"><strong>{fmt_int(t['min_threshold'])}</strong></td>
        <td></td>
        <td class="blue-h num"><strong>{fmt_int(t['stretch_goal'])}</strong></td>
        <td class="num"><strong>{fmt_int(t['actuals_mtd'])}</strong></td>
        <td class="num"><strong>{fmt_int(t['pacing'])}</strong></td>
        <td></td>
        <td class="{tot_cls} num"><strong>{fmt_pct(t['pct_stretch'])}</strong></td>
      </tr>""")
    html = f"""
    <table class="bordered">
      <tr class="gray-h">
        <th>Card</th><th>Month</th><th>CPA</th>
        <th class="blue-h">Minimum Threshold</th>
        <th class="blue-h">Tier Target</th>
        <th class="blue-h">Stretch Goal</th>
        <th>Actuals MTD</th>
        <th>Pacing</th>
        <th>Pacing vs. Minimum</th>
        <th>Pacing vs. Stretch Goal %</th>
      </tr>
      {''.join(rows)}
    </table>
    """
    return render_html_to_png(html, out_path, viewport_width=1500)


def _channel_block_html(channel_name: str, logo_emoji: str,
                        rows: list[dict], totals: dict) -> str:
    """One channel block for the Channel Sprint sections."""
    row_html = []
    for r in rows:
        pct_cls = pct_color(r["pct"]) if r.get("pct") is not None else "gray"
        row_html.append(f"""
        <tr>
          <td></td>
          <td class="label-col">{r['card_full_name']}</td>
          <td class="num">{r['cpa']}</td>
          <td class="blue-h num">{fmt_int(r['monthly_goal'])}</td>
          <td class="num">{fmt_int(r['actuals_mtd'])}</td>
          <td class="num">{fmt_int(r['pacing'])}</td>
          <td class="{pct_cls} num"><strong>{fmt_pct(r['pct'])}</strong></td>
        </tr>""")
    tot_cls = pct_color(totals.get("pct"))
    return f"""
    <table class="bordered channel-block">
      <tr class="gray-h">
        <td rowspan="{len(rows) + 2}" class="logo-cell">
          <div style="font-size:28px;">{logo_emoji}</div>
          <div style="font-weight:700; font-size:14px;">{channel_name}</div>
        </td>
        <th>Card</th>
        <th>CPA</th>
        <th class="blue-h">Monthly Goal</th>
        <th>Actuals MTD</th>
        <th>Pacing</th>
        <th>% Pacing to Goal</th>
      </tr>
      {''.join(row_html)}
      <tr class="totals-row">
        <td class="label-col"><strong>Totals</strong></td>
        <td></td>
        <td class="blue-h num"><strong>{fmt_int(totals['monthly_goal'])}</strong></td>
        <td class="num"><strong>{fmt_int(totals['actuals_mtd'])}</strong></td>
        <td class="num"><strong>{fmt_int(totals['pacing'])}</strong></td>
        <td class="{tot_cls} num"><strong>{fmt_pct(totals['pct'])}</strong></td>
      </tr>
    </table>
    """


def render_channel_sprint_1(payload: dict, out_path: Path) -> Path:
    """Image 8: Google Ads + Meta Ads stacked."""
    g = payload["google_ads"]
    m = payload["meta_ads"]
    html = (
        _channel_block_html("Google Ads", "🔵", g["rows"], g["totals"])
        + _channel_block_html("Meta Ads", "🔷", m["rows"], m["totals"])
    )
    return render_html_to_png(html, out_path, viewport_width=1300)


def render_channel_sprint_2(payload: dict, out_path: Path) -> Path:
    """Image 9: Bing Ads."""
    b = payload["bing_ads"]
    html = _channel_block_html("Bing", "🟢", b["rows"], b["totals"])
    return render_html_to_png(html, out_path, viewport_width=1300)


def render_channel_sprint_3(payload: dict, out_path: Path) -> Path:
    """Image 10: Google Organic + Direct/Other Traffic stacked."""
    g = payload["google_organic"]
    d = payload["direct_other"]
    html = (
        _channel_block_html("Google Organic", "🔎", g["rows"], g["totals"])
        + _channel_block_html("Direct/Other Traffic", "📩", d["rows"], d["totals"])
    )
    return render_html_to_png(html, out_path, viewport_width=1300)


def render_roas_bottom(payload: dict, out_path: Path) -> Path:
    """Image 11: Compact 3-channel ROAS recap."""
    blocks = []
    for ch in payload["channels"]:
        c_roas = pct_color(ch["roas"])
        blocks.append(f"""
        <table class="bordered roas-bottom" style="margin-bottom:10px;">
          <tr class="blue-h">
            <th>{ch['name']} ROAS<br/>(MTD)</th>
            <th>Profit/Loss<br/>(MTD)</th>
            <th>Spend</th>
          </tr>
          <tr>
            <td class="{c_roas} num"><strong>{fmt_pct(ch['roas'])}</strong></td>
            <td class="green-l num">{fmt_money(ch['profit'])}</td>
            <td class="num">{fmt_money(ch['spend'])}</td>
          </tr>
        </table>
        """)
    return render_html_to_png("".join(blocks), out_path, viewport_width=700)


# ----- Dispatcher --------------------------------------------------------

SECTIONS = {
    "pacing_1": render_pacing_1,
    "pacing_2": render_pacing_2,
    "pacing_3": render_pacing_3,
    "pacing_4": render_pacing_4,
    "roas_mid": render_roas_mid,
    "ns_google": render_ns_google_helper,
    "card_sprint": render_card_sprint,
    "channel_sprint_1": render_channel_sprint_1,
    "channel_sprint_2": render_channel_sprint_2,
    "channel_sprint_3": render_channel_sprint_3,
    "roas_bottom": render_roas_bottom,
}


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("Usage: render.py <section> <input.json> <out.png>",
              file=sys.stderr)
        print(f"Sections: {', '.join(SECTIONS.keys())}", file=sys.stderr)
        return 2
    section, in_path, out_path = argv[1], argv[2], argv[3]
    if section not in SECTIONS:
        print(f"Unknown section '{section}'. "
              f"Valid: {', '.join(SECTIONS.keys())}", file=sys.stderr)
        return 2
    payload = json.loads(Path(in_path).read_text())
    SECTIONS[section](payload, Path(out_path))
    print(f"OK {section} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
