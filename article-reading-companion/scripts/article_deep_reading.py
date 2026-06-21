#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKDIR = Path(os.environ.get("ARTICLE_DEEP_READING_WORKDIR", SKILL_DIR)).expanduser().resolve()
IMA_CONFIG = Path(os.environ.get("IMA_CONFIG_DIR", Path.home() / ".config" / "ima")).expanduser()
CACHE = WORKDIR / "cache"
LOGS = WORKDIR / "logs"
PROCESSED_PATH = WORKDIR / "processed.json"
CURRENT_PREPARE_PATH = CACHE / "current_prepare.json"
CURRENT_ARTICLE_PATH = CACHE / "current_article.md"
CURRENT_READER_PAYLOAD_PATH = CACHE / "current_reader_payload.json"
ATTENTION_PATH = CACHE / "attention_signal.md"
ATTENTION_OVERRIDE_PATH = WORKDIR / "attention_override.md"
READER_TEMPLATE_PATH = Path(
    os.environ.get("ARTICLE_DEEP_READING_TEMPLATE", SKILL_DIR / "assets" / "reader_template.html")
).expanduser()
READER_PAGES = WORKDIR / "reader_pages"
TARGET_KB_NAME = os.environ.get("ARTICLE_DEEP_READING_SOURCE_KB", "").strip()
MIN_BODY_CHARS = int(os.environ.get("ARTICLE_DEEP_READING_MIN_BODY_CHARS", "1000"))
MAX_FETCH_ATTEMPTS = int(os.environ.get("ARTICLE_DEEP_READING_MAX_FETCH_ATTEMPTS", "8"))
CANDIDATE_SHORTLIST_LIMIT = int(os.environ.get("ARTICLE_DEEP_READING_SHORTLIST_LIMIT", "15"))

CURATED_TERMS = [
    "AI原生组织", "AI 原生组织", "AI组织", "AI组织变革", "AI工作台", "AI 工作台",
    "Agent", "AI Agent", "多Agent", "智能体", "Skill", "SOP", "工作流",
    "知识库", "知识工程", "知识沉淀", "自动化", "评测", "门禁", "复盘",
    "产品经理", "项目管理", "项目协作", "PRD", "组织协作", "组织效率",
    "行业研究", "业务流程", "合规", "写作", "AI写作", "认知", "判断力",
]
CURATED_TERMS.extend(
    item.strip()
    for item in os.environ.get("ARTICLE_DEEP_READING_CURATED_TERMS", "").split(",")
    if item.strip()
)

QUESTION_MARKERS = (
    "如何", "怎么", "为什么", "能不能", "要不要", "是否", "有没有", "问题",
    "目标", "困惑", "关键", "风险", "缺口", "需要", "应该", "想清楚",
)

NOISE_TERMS = {
    "今日选文临时关注", "今日关注画像", "最新每日聚焦", "灵感收集", "项目状态",
    "当前问题", "优先主题", "知识缺口", "选文搜索词",
}

ANTI_BOT_RE = re.compile(
    r"环境异常|去验证|当前环境异常|访问过于频繁|请在微信客户端打开|安全验证|"
    r"完成验证后即可继续访问"
)


@dataclass
class Candidate:
    media_id: str
    title: str
    media_type: int
    query_hits: set[str] = field(default_factory=set)
    highlight: str = ""
    score: int = 0
    url: str = ""
    fit_reasons: list[str] = field(default_factory=list)


def fail(message: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    raise SystemExit(code)


def read_text(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit] if limit else text


def safe_filename(text: str, max_len: int = 120) -> str:
    text = re.sub(r"[\n\r\t]", " ", text)
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:max_len].strip() or "untitled")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not choose unique path for {path}")


def load_credentials() -> tuple[str, str]:
    client_id = (
        os.environ.get("IMA_OPENAPI_CLIENTID")
        or os.environ.get("IMA_CLIENT_ID")
        or read_text(IMA_CONFIG / "client_id").strip()
    )
    api_key = (
        os.environ.get("IMA_OPENAPI_APIKEY")
        or os.environ.get("IMA_API_KEY")
        or read_text(IMA_CONFIG / "api_key").strip()
    )
    if not client_id or not api_key:
        fail(
            "IMA credentials missing. Set IMA_OPENAPI_CLIENTID and IMA_OPENAPI_APIKEY, "
            "or configure IMA_CONFIG_DIR/client_id and IMA_CONFIG_DIR/api_key."
        )
    return client_id, api_key


def ima_post(api_path: str, body: dict[str, Any]) -> dict[str, Any]:
    client_id, api_key = load_credentials()
    req = urllib.request.Request(
        f"https://ima.qq.com/{api_path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "ima-openapi-clientid": client_id,
            "ima-openapi-apikey": api_key,
            "ima-openapi-ctx": "skill=article-reading-companion;source=oss",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        fail(f"IMA HTTP error: {exc.code} {exc.reason}")
    except Exception as exc:
        fail(f"IMA request failed: {exc}")
    if payload.get("code") != 0:
        fail(f"IMA API error at {api_path}: {payload.get('code')} {payload.get('msg')}")
    return payload.get("data") or {}


def list_of(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def get_kb_id() -> str:
    if not TARGET_KB_NAME:
        fail("ARTICLE_DEEP_READING_SOURCE_KB is required.")
    data = ima_post("openapi/wiki/v1/get_addable_knowledge_base_list", {"cursor": "", "limit": 50})
    for item in list_of(data, "addable_knowledge_base_list", "info_list"):
        if item.get("name") == TARGET_KB_NAME or item.get("kb_name") == TARGET_KB_NAME:
            return item.get("id") or item.get("kb_id") or item.get("knowledge_base_id") or ""
    fail(f"Knowledge base not found: {TARGET_KB_NAME}")
    return ""


def attention_source_paths() -> list[Path]:
    paths: list[Path] = []
    raw = os.environ.get("ARTICLE_DEEP_READING_ATTENTION_SOURCES", "")
    for item in raw.split(os.pathsep):
        item = item.strip()
        if item:
            paths.append(Path(item).expanduser())
    if ATTENTION_OVERRIDE_PATH.exists():
        paths.insert(0, ATTENTION_OVERRIDE_PATH)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def read_attention_source(path: Path, limit: int = 5000) -> tuple[str, list[str]]:
    if path.is_file():
        return read_text(path, limit), [str(path)]
    if not path.is_dir():
        return "", []

    files = [item for item in path.rglob("*.md") if item.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    parts: list[str] = []
    sources: list[str] = []
    for file_path in files[:8]:
        text = read_text(file_path, max(1200, limit // 4))
        if text:
            sources.append(str(file_path))
            parts.append(f"## {file_path.name}\n\n{text}")
    return "\n\n".join(parts), sources


def build_attention_signal() -> dict[str, Any]:
    parts: list[str] = []
    sources: list[str] = []

    for path in attention_source_paths():
        text, used_sources = read_attention_source(path)
        if text:
            sources.extend(used_sources)
            parts.append(f"# Reading focus source: {path.name}\n\n{text}")

    if not parts:
        parts.append(
            "# Reading focus\n\n"
            "No attention source is configured. The selector will fall back to broad article themes."
        )

    raw_signal = "\n\n---\n\n".join(parts)
    focus_profile = derive_focus_profile(raw_signal)
    signal = render_attention_signal(focus_profile, raw_signal)
    CACHE.mkdir(parents=True, exist_ok=True)
    ATTENTION_PATH.write_text(signal, encoding="utf-8")

    keywords = focus_profile["search_queries"]
    return {
        "attention_path": str(ATTENTION_PATH),
        "sources": sources,
        "keywords": keywords,
        "focus_profile": focus_profile,
    }


def render_attention_signal(profile: dict[str, Any], raw_signal: str) -> str:
    lines = [
        "# 今日关注画像",
        "",
        "## 当前问题",
        *[f"- {item}" for item in profile.get("current_questions", [])],
        "",
        "## 优先主题",
        *[f"- {item}" for item in profile.get("priority_terms", [])],
        "",
        "## 知识缺口",
        *[f"- {item}" for item in profile.get("knowledge_needs", [])],
        "",
        "## 选文搜索词",
        *[f"- {item}" for item in profile.get("search_queries", [])],
        "",
        "---",
        "",
        raw_signal,
    ]
    return "\n".join(lines).strip() + "\n"


def derive_focus_profile(signal: str) -> dict[str, Any]:
    terms = extract_priority_terms(signal, limit=20)
    questions = extract_current_questions(signal, terms, limit=8)
    knowledge_needs = derive_knowledge_needs(signal, terms)
    search_queries = derive_search_queries(signal, terms, questions)
    return {
        "current_questions": questions,
        "priority_terms": terms,
        "knowledge_needs": knowledge_needs,
        "search_queries": search_queries,
    }


def normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def add_unique(items: list[str], item: str, limit: int | None = None) -> None:
    item = re.sub(r"\s+", " ", item).strip(" -#>*`：:，,。；;")
    if not item or item in items:
        return
    if limit is not None and len(items) >= limit:
        return
    items.append(item)


def extract_priority_terms(signal: str, limit: int = 20) -> list[str]:
    normalized = normalize_match_text(signal)
    scored: dict[str, int] = {}
    for index, term in enumerate(CURATED_TERMS):
        compact = normalize_match_text(term)
        if compact and compact in normalized:
            scored[term.replace(" ", "")] = scored.get(term.replace(" ", ""), 0) + 100 - index

    for pattern in (r"\[\[([^\]]{2,30})\]\]", r"\*\*([^*]{2,30})\*\*", r"^#{1,4}\s+(.{2,40})$"):
        for match in re.findall(pattern, signal, flags=re.MULTILINE):
            text = re.sub(r"[#`*_()\[\]（）]", "", str(match)).strip()
            if 2 <= len(text) <= 24 and text not in NOISE_TERMS:
                scored[text] = scored.get(text, 0) + 18

    for match in re.findall(r"[A-Za-z][A-Za-z0-9+.-]{1,24}", signal):
        if len(match) >= 2 and match.lower() not in {"http", "https", "markdown"}:
            scored[match] = scored.get(match, 0) + 6

    for match in re.findall(r"[\u4e00-\u9fff]{2,10}", signal):
        if len(match) > 6:
            continue
        if any(marker in match for marker in ("今天", "这个", "一下", "可以", "然后", "就是", "如何", "怎么", "最近", "这些", "东西")):
            continue
        if match.endswith(("和", "与", "的", "成")) or match.startswith(("和", "与", "的")):
            continue
        if any(key in match for key in ("知识", "项目", "产品", "组织", "流程", "行业", "业务", "合规", "写作", "认知", "策略")):
            scored[match] = scored.get(match, 0) + 4

    defaults = ["AI", "Agent", "AI工作台", "知识库", "项目管理", "行业研究", "写作"]
    for item in defaults:
        scored.setdefault(item, 1)

    ordered = sorted(scored.items(), key=lambda pair: (pair[1], len(pair[0])), reverse=True)
    result: list[str] = []
    for term, _score in ordered:
        if len(result) >= limit:
            break
        if not any(normalize_match_text(term) == normalize_match_text(existing) for existing in result):
            result.append(term)
    return result


def extract_current_questions(signal: str, terms: list[str], limit: int = 8) -> list[str]:
    questions: list[str] = []
    for raw in reversed(signal.splitlines()):
        line = re.sub(r"\s+", " ", raw.strip(" -#>*`")).strip()
        if not line or len(line) < 8 or len(line) > 120:
            continue
        if "http" in line.lower():
            continue
        if "？" in line or "?" in line or any(marker in line for marker in QUESTION_MARKERS):
            add_unique(questions, line, limit)
        if len(questions) >= limit:
            break

    if not questions:
        for term in terms[:5]:
            add_unique(questions, f"最近围绕「{term}」有什么新框架、反例或可落地方法？", limit)
    return questions


def derive_knowledge_needs(signal: str, terms: list[str]) -> list[str]:
    needs: list[str] = []
    normalized = normalize_match_text(signal)
    if any(token in normalized for token in ("项目", "prd", "需求", "协作", "推进")):
        add_unique(needs, "能直接帮助当前项目判断、推进或设计的案例和方法")
    if any(token in normalized for token in ("ai工作台", "agent", "skill", "自动化", "工作流")):
        add_unique(needs, "可沉淀为 AI 工作台、Agent 或 Skill 设计规则的经验")
    if any(token in normalized for token in ("行业", "业务", "领域", "合规")):
        add_unique(needs, "能补充具体行业、业务流程或合规判断的结构化知识")
    if any(token in normalized for token in ("写作", "表达", "公众号")):
        add_unique(needs, "可转化为写作选题、表达框架或观点素材的洞察")
    if any(token in normalized for token in ("认知", "判断力", "价值")):
        add_unique(needs, "能更新个人认知、判断力或长期方法的洞察")
    for term in terms[:3]:
        add_unique(needs, f"围绕「{term}」补一个能改变判断的高质量观点或反例")
    return needs[:8]


def derive_search_queries(signal: str, terms: list[str], questions: list[str]) -> list[str]:
    result: list[str] = []
    for term in terms:
        add_unique(result, term)
    for question in questions:
        for term in terms[:8]:
            if normalize_match_text(term) in normalize_match_text(question):
                add_unique(result, term)
    defaults = ["AI", "Agent", "Skill", "知识库", "项目管理", "行业研究", "写作", "公众号"]
    for word in defaults:
        add_unique(result, word)
    return result[:24]


def load_processed() -> dict[str, Any]:
    if not PROCESSED_PATH.exists():
        return {"items": []}
    try:
        data = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"items": []}
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


def processed_keys() -> set[str]:
    data = load_processed()
    keys: set[str] = set()
    for item in data.get("items", []):
        for key in ("media_id", "url", "title"):
            if item.get(key):
                keys.add(str(item[key]))
    return keys


def item_media_id(item: dict[str, Any]) -> str:
    return str(item.get("media_id") or item.get("id") or item.get("content_id") or "")


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or "")


def item_media_type(item: dict[str, Any]) -> int:
    value = item.get("media_type")
    try:
        return int(value)
    except Exception:
        return -1


def collect_candidates(kb_id: str, keywords: list[str], focus_profile: dict[str, Any]) -> list[Candidate]:
    candidates: dict[str, Candidate] = {}

    root = ima_post(
        "openapi/wiki/v1/get_knowledge_list",
        {"knowledge_base_id": kb_id, "cursor": "", "limit": 50},
    )
    for rank, item in enumerate(list_of(root, "knowledge_list")):
        if item_media_type(item) != 6:
            continue
        mid = item_media_id(item)
        if not mid:
            continue
        cand = candidates.setdefault(mid, Candidate(mid, item_title(item), 6))
        cand.score += max(0, 50 - rank)

    for keyword in keywords:
        data = ima_post(
            "openapi/wiki/v1/search_knowledge",
            {"query": keyword, "knowledge_base_id": kb_id, "cursor": ""},
        )
        for item in list_of(data, "info_list"):
            if item_media_type(item) != 6:
                continue
            mid = item_media_id(item)
            if not mid:
                continue
            title = item_title(item)
            highlight = str(item.get("highlight_content") or "")
            cand = candidates.setdefault(mid, Candidate(mid, title, 6))
            cand.title = cand.title or title
            cand.highlight = cand.highlight or highlight
            cand.query_hits.add(keyword)
            cand.score += 10
            if keyword.lower() in f"{title} {highlight}".lower():
                cand.score += 15

    seen = processed_keys()
    filtered = [
        cand for cand in candidates.values()
        if cand.media_id not in seen and cand.title not in seen
    ]
    score_candidates_against_focus(filtered, focus_profile)
    filtered.sort(key=lambda c: (c.score, len(c.query_hits)), reverse=True)
    return filtered


def score_candidates_against_focus(candidates: list[Candidate], profile: dict[str, Any]) -> None:
    priority_terms = list(profile.get("priority_terms") or [])
    knowledge_needs = list(profile.get("knowledge_needs") or [])
    current_questions = list(profile.get("current_questions") or [])

    for cand in candidates:
        text = f"{cand.title} {cand.highlight}"
        compact_text = normalize_match_text(text)
        compact_title = normalize_match_text(cand.title)
        reasons: list[str] = []

        for rank, term in enumerate(priority_terms[:20]):
            compact_term = normalize_match_text(term)
            if not compact_term:
                continue
            if compact_term in compact_title:
                boost = max(12, 34 - rank)
                cand.score += boost
                add_unique(reasons, f"标题命中关注主题「{term}」")
            elif compact_term in compact_text:
                boost = max(6, 18 - rank // 2)
                cand.score += boost
                add_unique(reasons, f"摘要命中关注主题「{term}」")

        for query in cand.query_hits:
            if any(normalize_match_text(query) in normalize_match_text(term) for term in priority_terms[:12]):
                cand.score += 8
                add_unique(reasons, f"搜索词「{query}」来自今日关注画像")

        for need in knowledge_needs:
            if any(token in compact_text for token in ("方法", "框架", "案例", "实践", "复盘", "规则", "组织", "流程")):
                cand.score += 5
                add_unique(reasons, "可能提供方法、案例或规则，适合沉淀")
                break

        if any(token in compact_title for token in ("快讯", "日报", "周报", "融资", "发布会", "榜单")):
            cand.score -= 18
            add_unique(reasons, "标题偏资讯流，降低深读优先级")

        if any(token in compact_text for token in ("深度", "方法", "框架", "复盘", "实践", "案例", "组织", "工作流")):
            cand.score += 10
            add_unique(reasons, "更像可深读的方法/实践文章")

        if not reasons and current_questions:
            add_unique(reasons, "与今日关注画像弱相关，仅作为备选")
        cand.fit_reasons = reasons[:5]


def candidate_summary(candidate: Candidate) -> dict[str, Any]:
    return {
        "title": candidate.title,
        "score": candidate.score,
        "query_hits": sorted(candidate.query_hits),
        "fit_reasons": candidate.fit_reasons,
        "highlight": re.sub(r"\s+", " ", candidate.highlight).strip()[:240],
    }


def get_media_url(candidate: Candidate) -> str:
    data = ima_post("openapi/wiki/v1/get_media_info", {"media_id": candidate.media_id})
    url = ((data.get("url_info") or {}).get("url") or "").strip()
    if not url:
        raise RuntimeError("get_media_info did not return url_info.url")
    candidate.url = url
    return url


def markdown_cli() -> Path:
    configured = os.environ.get("WECHAT_ARTICLE_TO_MARKDOWN", "").strip()
    if configured:
        exe = Path(configured).expanduser()
        if exe.exists():
            return exe
        fail(f"WECHAT_ARTICLE_TO_MARKDOWN does not exist: {exe}")

    local = WORKDIR / ".venv" / "bin" / "wechat-article-to-markdown"
    if local.exists():
        return local

    found = shutil.which("wechat-article-to-markdown")
    if found:
        return Path(found)

    fail(
        "wechat-article-to-markdown not found. Install it in PATH, "
        "create WORKDIR/.venv, or set WECHAT_ARTICLE_TO_MARKDOWN."
    )
    return Path("wechat-article-to-markdown")


def fetch_markdown(url: str, title: str) -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"fetch-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    start = time.time()
    proc = subprocess.run(
        [str(markdown_cli()), url],
        cwd=str(WORKDIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=150,
    )
    output = proc.stdout or ""
    log_path.write_text(output, encoding="utf-8", errors="replace")
    saved = parse_saved_path(output)
    if proc.returncode != 0:
        raise RuntimeError(f"wechat markdown command failed, see {log_path}")
    if not saved or not saved.exists():
        raise RuntimeError(f"markdown output path not found, see {log_path}")

    text = saved.read_text(encoding="utf-8", errors="replace")
    validate_markdown(text)
    CACHE.mkdir(parents=True, exist_ok=True)
    CURRENT_ARTICLE_PATH.write_text(text, encoding="utf-8")
    source_output_removed = cleanup_source_output(saved)
    return {
        "source_output_path": str(saved),
        "source_output_removed": source_output_removed,
        "article_markdown_path": str(CURRENT_ARTICLE_PATH),
        "body_chars": len(text),
        "body_bytes": len(text.encode("utf-8")),
        "body_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "fetch_seconds": round(time.time() - start, 1),
        "fetch_log_path": str(log_path),
    }


def parse_saved_path(output: str) -> Path | None:
    matches = re.findall(r"已保存:\s*(.+?\.md)", output)
    if not matches:
        return None
    path = Path(matches[-1].strip())
    if not path.is_absolute():
        path = WORKDIR / path
    return path


def cleanup_source_output(saved: Path) -> bool:
    try:
        saved = saved.resolve()
        workdir = WORKDIR.resolve()
        saved.relative_to(workdir)
    except Exception:
        return False
    if "output" not in saved.parts:
        return False
    try:
        shutil.rmtree(saved.parent)
        return True
    except Exception:
        return False


def validate_markdown(text: str) -> None:
    plain = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
    plain = re.sub(r"[`*_#>\-\[\]()]+", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) < MIN_BODY_CHARS:
        raise RuntimeError(f"markdown body too short: {len(plain)} chars")
    if ANTI_BOT_RE.search(text):
        raise RuntimeError("markdown contains anti-bot marker")


def prepare() -> None:
    attention = build_attention_signal()
    kb_id = get_kb_id()
    candidates = collect_candidates(kb_id, attention["keywords"], attention.get("focus_profile", {}))
    if not candidates:
        fail("No unprocessed WeChat article candidates found.", code=0)

    attempts: list[dict[str, Any]] = []
    selected: Candidate | None = None
    fetched: dict[str, Any] | None = None
    for candidate in candidates[:MAX_FETCH_ATTEMPTS]:
        try:
            url = get_media_url(candidate)
            fetched = fetch_markdown(url, candidate.title)
            selected = candidate
            attempts.append({
                "title": candidate.title,
                "ok": True,
                "score": candidate.score,
                "query_hits": sorted(candidate.query_hits),
                "fit_reasons": candidate.fit_reasons,
            })
            break
        except Exception as exc:
            attempts.append({
                "title": candidate.title,
                "ok": False,
                "score": candidate.score,
                "query_hits": sorted(candidate.query_hits),
                "fit_reasons": candidate.fit_reasons,
                "error": str(exc),
            })

    if not selected or not fetched:
        payload = {
            "ok": False,
            "error": "All candidate fetch attempts failed.",
            "attempts": attempts,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(0)

    selected_reason = build_selected_reason(selected, attention)
    candidate_shortlist = [candidate_summary(candidate) for candidate in candidates[:CANDIDATE_SHORTLIST_LIMIT]]
    payload = {
        "ok": True,
        "prepared_at": datetime.now().isoformat(timespec="seconds"),
        "knowledge_base_name": TARGET_KB_NAME,
        "title": selected.title,
        "url": selected.url,
        "media_id": selected.media_id,
        "score": selected.score,
        "query_hits": sorted(selected.query_hits),
        "selected_reason": selected_reason,
        "candidate_shortlist": candidate_shortlist,
        "attention": attention,
        "attempts": attempts,
        **fetched,
        "sha12": fetched["body_sha256"][:12],
        "commit_command": "./run_daily.sh commit",
    }
    CURRENT_PREPARE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_selected_reason(candidate: Candidate, attention: dict[str, Any]) -> str:
    hits = "、".join(sorted(candidate.query_hits)) or "根目录近期条目"
    profile = attention.get("focus_profile") or {}
    questions = profile.get("current_questions") or []
    needs = profile.get("knowledge_needs") or []
    reasons = "；".join(candidate.fit_reasons[:3]) or "在候选池中综合得分靠前"
    question = f"当前关注问题：{questions[0]}。" if questions else ""
    need = f"对应知识缺口：{needs[0]}。" if needs else ""
    return (
        f"这篇文章命中了今日关注画像中的「{hits}」，在候选池中得分 {candidate.score}。"
        f"{question}{need}"
        f"选中理由：{reasons}。"
        "请在深读时继续判断它是否真的补足当前项目、知识库、写作或个人思考中的缺口。"
    )


def commit() -> None:
    if not CURRENT_PREPARE_PATH.exists():
        fail("No current prepare payload found.")
    payload = json.loads(CURRENT_PREPARE_PATH.read_text(encoding="utf-8"))
    if not payload.get("ok"):
        fail("Current prepare payload is not successful.")

    data = load_processed()
    items = data.setdefault("items", [])
    if not any(item.get("media_id") == payload.get("media_id") for item in items):
        items.append({
            "processed_at": datetime.now().isoformat(timespec="seconds"),
            "title": payload.get("title"),
            "url": payload.get("url"),
            "media_id": payload.get("media_id"),
            "body_chars": payload.get("body_chars"),
            "sha12": payload.get("sha12"),
            "query_hits": payload.get("query_hits", []),
        })
    PROCESSED_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if CURRENT_ARTICLE_PATH.exists():
        CURRENT_ARTICLE_PATH.unlink()
    print(json.dumps({
        "ok": True,
        "processed_count": len(items),
        "title": payload.get("title"),
        "sha12": payload.get("sha12"),
    }, ensure_ascii=False, indent=2))


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"reader payload missing {label}")
    return value.strip()


def normalize_reader_payload(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise RuntimeError("reader payload missing meta")
    meta["title"] = require_text(meta.get("title"), "meta.title")
    meta["url"] = require_text(meta.get("url"), "meta.url")
    if not isinstance(meta.get("source"), str):
        meta["source"] = ""

    guide = data.get("guide")
    if not isinstance(guide, dict):
        raise RuntimeError("reader payload missing guide")
    guide["question"] = require_text(guide.get("question"), "guide.question")
    guide["summary"] = require_text(guide.get("summary"), "guide.summary")
    chain = guide.get("chain")
    if isinstance(chain, str):
        guide["chain"] = [part.strip() for part in re.split(r"\s*(?:->|→|/)\s*", chain) if part.strip()]
    if not isinstance(guide.get("chain"), list) or not guide["chain"]:
        raise RuntimeError("reader payload missing guide.chain")

    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise RuntimeError("reader payload missing blocks")

    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            raise RuntimeError(f"reader payload block {index} is not an object")
        block["id"] = str(block.get("id") or f"b{index}")
        block["kicker"] = str(block.get("kicker") or f"{index:02d}")
        block["title"] = require_text(block.get("title"), f"blocks[{index}].title")
        block["position"] = require_text(block.get("position"), f"blocks[{index}].position")
        source_markdown = block.get("source_markdown") or block.get("source")
        block["source_markdown"] = require_text(source_markdown, f"blocks[{index}].source_markdown")

        analysis = block.get("analysis")
        if not isinstance(analysis, dict):
            raise RuntimeError(f"reader payload block {index} missing analysis")
        if not analysis.get("本块一句话"):
            merged = "；".join(
                str(analysis.get(key, "")).strip()
                for key in ("原文原意", "作者证据")
                if str(analysis.get(key, "")).strip()
            )
            if merged:
                analysis["本块一句话"] = merged
        for label in ("本块一句话", "主论点", "子论点", "事实核查 / 可信度"):
            if label not in analysis:
                raise RuntimeError(f"reader payload block {index} missing analysis.{label}")
        if "信息缺口 / 反例" not in analysis and "信息缺口" in analysis:
            analysis["信息缺口 / 反例"] = analysis["信息缺口"]
        if "信息缺口 / 反例" not in analysis:
            raise RuntimeError(f"reader payload block {index} missing analysis.信息缺口 / 反例")
        for legacy_key in ("原文原意", "作者证据", "信息缺口", "对 PM 的业务帮助", "可沉淀建议"):
            analysis.pop(legacy_key, None)

    synthesis = data.get("synthesis")
    if not isinstance(synthesis, dict):
        synthesis = {}
        data["synthesis"] = synthesis
    synthesis["title"] = str(synthesis.get("title") or "本文洞察与行动建议")
    insights = synthesis.get("insights")
    if not isinstance(insights, list):
        synthesis["insights"] = []
    items = synthesis.get("items")
    if not isinstance(items, list):
        synthesis["items"] = []

    return data


def render_reader(args: argparse.Namespace) -> None:
    payload_path = Path(args.payload)
    if not payload_path.is_absolute():
        payload_path = WORKDIR / payload_path
    if not payload_path.exists():
        fail(f"Reader payload not found: {payload_path}")
    if not READER_TEMPLATE_PATH.exists():
        fail(f"Reader template not found: {READER_TEMPLATE_PATH}")

    try:
        data = json.loads(payload_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("reader payload root must be an object")
        data = normalize_reader_payload(data)
    except Exception as exc:
        fail(f"Invalid reader payload: {exc}")

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = WORKDIR / output_path
    else:
        READER_PAGES.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        name = safe_filename(f"{today}-{data['meta']['title']}-陪读", max_len=150)
        output_path = unique_path(READER_PAGES / f"{name}.html")

    template = READER_TEMPLATE_PATH.read_text(encoding="utf-8")
    json_text = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    html = template.replace("__READER_DATA_JSON__", json_text)
    if "__READER_DATA_JSON__" in html:
        fail("Reader template placeholder was not replaced.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "title": data["meta"]["title"],
        "url": data["meta"]["url"],
        "html_path": str(output_path),
        "block_count": len(data["blocks"]),
        "insight_count": len(data.get("synthesis", {}).get("insights", [])),
        "synthesis_count": len(data.get("synthesis", {}).get("items", [])),
    }, ensure_ascii=False, indent=2))


def status() -> None:
    data = load_processed()
    print(json.dumps({
        "ok": True,
        "workdir": str(WORKDIR),
        "processed_count": len(data.get("items", [])),
        "has_current_prepare": CURRENT_PREPARE_PATH.exists(),
        "has_current_article": CURRENT_ARTICLE_PATH.exists(),
        "has_current_reader_payload": CURRENT_READER_PAYLOAD_PATH.exists(),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sub.add_parser("commit")
    sub.add_parser("status")
    render_parser = sub.add_parser("render")
    render_parser.add_argument("--payload", default=str(CURRENT_READER_PAYLOAD_PATH))
    render_parser.add_argument("--output", default="")
    args = parser.parse_args()

    if args.cmd == "prepare":
        prepare()
    elif args.cmd == "commit":
        commit()
    elif args.cmd == "status":
        status()
    elif args.cmd == "render":
        render_reader(args)


if __name__ == "__main__":
    main()
