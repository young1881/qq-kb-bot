import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BOCHA_SEARCH_URL = "https://api.bocha.cn/v1/web-search"


def _bool_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _search_config() -> dict[str, object]:
    return {
        "api_key": os.getenv("BOCHA_API_KEY", "").strip(),
        "enabled": _bool_env("BOCHA_SEARCH_ENABLED", True),
        "count": _int_env("BOCHA_SEARCH_COUNT", 6, 1, 10),
        "timeout": _int_env("BOCHA_SEARCH_TIMEOUT", 8, 2, 30),
    }


def _trim(text: object, limit: int = 500) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _web_search_sync(query: str, cfg: dict[str, object]) -> list[dict[str, str]]:
    payload = json.dumps(
        {
            "query": query,
            "freshness": "noLimit",
            "summary": True,
            "count": cfg["count"],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        BOCHA_SEARCH_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=float(cfg["timeout"])) as response:
        raw = response.read().decode("utf-8")

    body = json.loads(raw)
    if body.get("code") != 200:
        logger.warning("博查搜索返回异常: code={}, msg={}", body.get("code"), body.get("msg"))
        return []

    pages = ((body.get("data") or {}).get("webPages") or {}).get("value") or []
    results = []
    for page in pages:
        title = _trim(page.get("name"), 120)
        url = _trim(page.get("url"), 300)
        if not title or not url:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "site": _trim(page.get("siteName"), 80),
                "date": _trim(page.get("datePublished") or page.get("dateLastCrawled"), 40),
                "snippet": _trim(page.get("summary") or page.get("snippet"), 500),
            }
        )
    return results


async def search_web(query: str) -> list[dict[str, str]]:
    cfg = _search_config()
    if not cfg["enabled"]:
        return []
    if not cfg["api_key"]:
        logger.info("BOCHA_API_KEY 未配置，跳过联网搜索")
        return []

    try:
        return await asyncio.to_thread(_web_search_sync, query.strip(), cfg)
    except urllib.error.HTTPError as exc:
        logger.warning("博查搜索 HTTP 异常: status={}", exc.code)
    except urllib.error.URLError as exc:
        logger.warning("博查搜索网络异常: {}", exc.reason)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("博查搜索响应解析失败: {}", exc)
    except Exception as exc:
        logger.warning("博查搜索请求失败: {}", exc)
    return []
