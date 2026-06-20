---
name: article-reading-companion
description: Run or maintain an article companion-reading workflow that selects saved WeChat articles, fetches article Markdown, and generates structured notes and two-column companion HTML pages. Use when the user asks for 文章伴读助手, article deep reading, companion reading, IMA-sourced WeChat article processing, or workflow maintenance.
---

# 文章伴读助手

Use this skill when the user wants to:

- select a saved article from an IMA knowledge base;
- fetch a full `mp.weixin.qq.com` article as Markdown;
- generate a structured deep-reading note and a fixed companion-reading HTML page;
- maintain the methodology, renderer, or daily automation for this workflow.

## What This Skill Does

The workflow has four stages:

1. Build a reading focus from optional local attention files.
2. Search an IMA knowledge base for unprocessed WeChat article candidates.
3. Fetch and validate the selected article Markdown.
4. Generate a deep-reading note and a companion page from `references/summary_methodology.md`.

The default source adapter is IMA OpenAPI. Credentials must come from environment variables or a local config directory; never store credentials in the repository.

## Required Files

- `references/summary_methodology.md`: the content method and output contract.
- `scripts/article_deep_reading.py`: prepare, render, status, and commit helper.
- `assets/reader_template.html`: fixed companion-reading page template.

## Commands

Prepare one article:

```bash
python3 scripts/article_deep_reading.py prepare
```

Render a companion page from a model-generated payload:

```bash
python3 scripts/article_deep_reading.py render --payload cache/current_reader_payload.json
```

Mark the prepared article as processed after the note and page are successfully generated:

```bash
python3 scripts/article_deep_reading.py commit
```

Inspect local state:

```bash
python3 scripts/article_deep_reading.py status
```

## Operating Rules

- Read `references/summary_methodology.md` before producing any note or payload.
- Do not summarize from title, highlight, or search snippets only. Use the fetched article Markdown.
- If the body is too short, empty, advertisement-only, or blocked by WeChat verification, stop and report failure.
- Keep full article text out of long-term Markdown archives unless the user explicitly wants a local companion page.
- Do not expose IMA media IDs, API keys, client IDs, local temp paths, or credential file paths in user-facing output.
- Generate the companion page from structured JSON and `assets/reader_template.html`; do not hand-write a fresh HTML layout for each article.
