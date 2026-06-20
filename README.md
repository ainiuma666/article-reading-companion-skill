# 文章伴读助手

An open-source Codex skill for turning saved WeChat articles into a companion-reading experience.

The workflow selects a relevant article from an IMA knowledge base, fetches the full article Markdown, generates a structured deep-reading note, and renders a fixed two-column HTML page: article blocks on the left, matching analysis on the right.

## What Is Included

- `article-reading-companion/`: the installable Codex skill.
- `article-reading-companion/scripts/article_deep_reading.py`: prepare, render, status, and commit helper.
- `article-reading-companion/assets/reader_template.html`: fixed companion-reading HTML template.
- `article-reading-companion/references/summary_methodology.md`: the reading and output methodology.
- `.env.example`: safe configuration template.
- `automation.example.toml`: example automation prompt.
- `examples/`: small synthetic examples for review and rendering tests.

## What Is Not Included

- API keys or client IDs.
- Local knowledge-base paths.
- Cached article Markdown.
- Logs, processed history, or generated reader pages.
- Any private archive structure.

## Setup

1. Copy `.env.example` to `.env` and fill in your own values.
2. Install dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

3. Run from the skill directory:

```bash
cd article-reading-companion
source ../.env
./scripts/run_daily.sh status
```

## Main Commands

Prepare an article:

```bash
./scripts/run_daily.sh prepare
```

Render a companion page:

```bash
./scripts/run_daily.sh render --payload cache/current_reader_payload.json
```

Mark the prepared article as processed:

```bash
./scripts/run_daily.sh commit
```

## Configuration

Required:

- `IMA_OPENAPI_CLIENTID`
- `IMA_OPENAPI_APIKEY`
- `ARTICLE_DEEP_READING_SOURCE_KB`

Useful optional variables:

- `ARTICLE_DEEP_READING_WORKDIR`
- `ARTICLE_DEEP_READING_ATTENTION_SOURCES`
- `ARTICLE_DEEP_READING_CURATED_TERMS`
- `ARTICLE_DEEP_READING_MIN_BODY_CHARS`
- `WECHAT_ARTICLE_TO_MARKDOWN`

See `.env.example` for details.

## Safety Notes

The companion HTML page may contain article text for local reading. Do not publish generated pages if the source article is not yours to redistribute. The long-term Markdown note should keep only the original link, position descriptions, and analysis.

## License

MIT. Change the license before publishing if you want a different open-source policy.
