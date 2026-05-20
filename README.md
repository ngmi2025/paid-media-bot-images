# Paid Media Bot — Image CDN

Public CDN for images embedded in the weekly Paid Media Tracking Report on Notion.

The bot (running as an Anthropic cloud Routine each Monday) generates 4 PNGs per week — pacing & tier tables, ROAS section, CARD SPRINT summary, and CHANNEL SPRINT breakdown — and uploads them here so Notion can embed them as native images.

## How it works

- Each Monday morning, the routine renders PNGs via Playwright + headless Chrome
- Uploads via GitHub Contents API (`PUT /repos/.../contents/{path}`) with random UUIDs for filenames
- Notion embeds them as native image blocks via `raw.githubusercontent.com` URLs
- This repo is essentially a write-only, never-deleted image archive

## Privacy

The PNGs contain Upgraded Points' paid media tracking visualisations (card pacing, ROAS, channel performance). Don't share random repo URLs externally.

## Files

```
{YYYY-MM-DD}/{uuid}.png
```

Date-stamped folders, UUID filenames so URLs aren't guessable.
