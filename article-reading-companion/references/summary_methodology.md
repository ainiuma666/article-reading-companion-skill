# 文章伴读助手方法论

## Purpose

This file is the content contract for `article-reading-companion`.

The goal is not to produce a decorative summary report. The goal is to create a companion-reading workspace: the reader can see the article structure, understand each logic block, inspect credibility and gaps, and decide what is worth acting on or saving.

## Inputs

Before generating a note or page, read all available inputs:

- `prepare` JSON output.
- `article_markdown_path` from the prepare JSON.
- `attention.attention_path`, `attention.focus_profile`, and `candidate_shortlist`.
- this methodology file.

Do not generate from title, highlight, IMA snippets, or partial excerpts only.

For external fact checks, verify only facts that materially affect the author's argument: numbers, dates, policies, company/product claims, papers, reports, releases, or comparable statements. Prefer primary or authoritative sources. Do not turn fact checking into a separate research essay.

## Article Selection

The selector should find an article that helps the current reading focus, not merely a generally relevant article.

When explaining the selection, cover:

1. Which focus question or knowledge gap the article matches.
2. Why this article is worth deep reading compared with ordinary news or weakly related candidates.
3. Whether the article should be downgraded as only weakly relevant.

## Core Reading Method

Extract the article's argument skeleton before writing:

1. Split the article in original order. Do not reorder blocks by your own preferred themes.
2. For each block, extract `problem / claim / subclaims / evidence / inference / conclusion`.
3. If the article does not support an item, write `not developed in the article` or `needs verification`.
4. Identify what the author wants the reader to believe, not just what the paragraph is about.
5. Write subclaims as complete units: claim, evidence, explanation, and proof strength.
6. Attach information gaps and fact checks to the relevant block instead of placing them in isolated sections.
7. After all blocks, synthesize article-level insights and action suggestions.

## Output Shape

Every generated deep-reading note should follow this shape:

```markdown
> Original article: [title](url)
> Selection reason:
> Companion page: [open local HTML](html_path)

# Title - Deep Reading

## Full Guide

**Question addressed**:

**One-sentence summary**:

**Argument chain**:
problem / context -> author claim -> evidence or cases -> method abstraction -> conclusion

## Block-by-Block Reading

### Block title in original order

| Field | Content |
|---|---|
| Original position | Position only. Do not paste the full article. |
| Block summary | 50-120 Chinese characters or 1-2 concise English sentences. |
| Main claim | The author's real judgment in this block. |
| Subclaims | Each item includes claim / evidence / explanation / proof strength. |
| Fact check / credibility | Attach verification results to specific claims. Use `needs verification` when unsure. |
| Gaps / counterexamples | Missing information, possible counterexamples, and whether they affect understanding or implementation. |

## Synthesis and Action Suggestions

### Insights

| Insight | Related block | Why it matters | Boundary or counterexample |
|---|---|---|---|

### Suggested Next Actions

| Suggestion | Related insight | Suggested destination | Next action | Priority |
|---|---|---|---|---|
```

## Companion Page Payload

The HTML page must be generated from a structured JSON payload and the fixed template in `assets/reader_template.html`.

Payload structure:

```json
{
  "meta": {
    "title": "Article title",
    "source": "Publisher name, optional",
    "url": "https://mp.weixin.qq.com/..."
  },
  "guide": {
    "question": "What problem this article addresses",
    "summary": "One-sentence summary",
    "chain": ["problem", "claim", "evidence", "method", "conclusion"]
  },
  "blocks": [
    {
      "id": "b1",
      "title": "Block title",
      "position": "Original position",
      "source_markdown": "Markdown for this block, used only in the local companion page",
      "analysis": {
        "本块一句话": "A concise block summary",
        "主论点": "Main claim",
        "子论点": [
          {
            "论点": "Subclaim",
            "依据": "Article evidence or `not developed in the article`",
            "解释": "Why the evidence supports the claim",
            "证明强度": "strong / medium / weak / not developed"
          }
        ],
        "事实核查 / 可信度": "Verification result or needs verification",
        "信息缺口 / 反例": "Gaps, counterexamples, implementation risks"
      }
    }
  ],
  "synthesis": {
    "title": "Synthesis and Action Suggestions",
    "insights": [
      {
        "洞察": "Article-level insight",
        "对应原文块": "Related block",
        "为什么对我重要": "Why it matters",
        "可能反例或边界": "Boundary or counterexample"
      }
    ],
    "items": [
      {
        "建议": "Concrete suggestion",
        "对应洞察": "Related insight",
        "建议去向": "Archive / project candidate / writing candidate / personal system candidate / do not save",
        "后续动作": "Next action",
        "优先级": "high / medium / low"
      }
    ]
  }
}
```

## Page Rules

- Put the full guide at the top of the page, spanning both columns.
- Use left column for article blocks and right column for the matching interpretation.
- Keep the right column focused on: block summary, main claim, subclaims, fact check / credibility, and gaps / counterexamples.
- Put synthesis and action suggestions at the end as a separate final view.
- Do not display operational metadata such as body size, hashes, internal IDs, temp paths, or credential locations.
- Do not use tag-heavy decorative blocks for the argument chain; keep it readable and plain.

## Quality Bar

- The result should be a dense assisted-reading product, not a pretty but disconnected summary.
- A reader should understand the article's content, argument, credibility, and usefulness without reading the full original article first.
- All fact checks and gaps must map back to a specific article block.
- All synthesis items must map back to one or more article blocks.
- Do not expose IMA internal IDs, API keys, client IDs, local temp paths, or private archive paths.
- If the article cannot be fetched or validated, stop. Do not generate a note, page, or processed marker.
