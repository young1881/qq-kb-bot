import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "kb.jsonl"

SOURCES = [
    {
        "path": ROOT / "source" / "100_rule.md",
        "doc": "100档规则",
        "default_section": "100档规则与更新",
    },
    {
        "path": ROOT / "source" / "黎明杀饥.md",
        "doc": "黎明杀饥模式",
        "default_section": "黎明杀饥模式",
    },
]


def clean_text(text: str) -> str:
    text = re.sub(r"<img\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:font|span|strong|em|u|p|div)\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r":::[a-zA-Z0-9_-]*", "", text)
    text = text.replace(":::", "")
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1：\2", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    text = text.replace("****", "")
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def strip_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+)$", line)
    if not match:
        return None
    title = clean_text(match.group(2)).strip(" #")
    if not title:
        return None
    return len(match.group(1)), title


def synthetic_heading(line: str) -> str | None:
    cleaned = clean_text(line).strip()
    if not cleaned:
        return None
    if re.match(r"^\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?\s*更新$", cleaned):
        return cleaned
    if re.match(r"^\d+(?:\.\d+)?\s*更新$", cleaned):
        return cleaned
    if re.match(r"^[一二三四五六七八九十]+、.+", cleaned):
        return cleaned
    return None


def normalize_body_line(line: str) -> str:
    line = clean_text(line)
    line = re.sub(r"^\s*>\s?", "", line)
    line = re.sub(r"^\s*[-+*]\s+", "- ", line)
    line = re.sub(r"^\s*(\d+)\.\s+", r"\1. ", line)
    return line.strip()


def iter_sections(source: dict) -> list[dict]:
    path = source["path"]
    lines = path.read_text(encoding="utf-8").splitlines()
    sections: list[dict] = []
    stack: list[tuple[int, str]] = [(1, source["doc"])]
    current_title = source["default_section"]
    current_level = 2
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        cleaned_body = [line for line in body if line]
        if cleaned_body:
            parents = [title for level, title in stack if level < current_level]
            sections.append(
                {
                    "doc": source["doc"],
                    "title": current_title,
                    "parents": parents,
                    "body": cleaned_body,
                }
            )
        body = []

    for raw in lines:
        heading = strip_heading(raw)
        synth = None if heading else synthetic_heading(raw)
        if heading or synth:
            flush()
            if heading:
                current_level, current_title = heading
            else:
                current_level, current_title = 2, synth or source["default_section"]

            stack = [item for item in stack if item[0] < current_level]
            if not stack:
                stack = [(1, source["doc"])]
            stack.append((current_level, current_title))
            continue

        line = normalize_body_line(raw)
        if line:
            body.append(line)

    flush()
    return sections


def chunk_lines(lines: list[str], limit: int = 1200) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + 1
        if current and size + extra > limit:
            chunks.append(current)
            current = []
            size = 0
        current.append(line)
        size += extra
    if current:
        chunks.append(current)
    return chunks


def compact_context(section: dict) -> str:
    names = []
    for name in [*section["parents"], section["title"]]:
        if name and name not in names:
            names.append(name)
    return " / ".join(names)


def question_variants(section: dict, part: int | None = None) -> list[str]:
    doc = section["doc"]
    title = section["title"]
    parents = [p for p in section["parents"] if p != doc]
    base = title if part is None else f"{title} 第{part}部分"
    variants = [
        base,
        f"{doc} {base}",
        f"{base} 是什么",
        f"{base} 规则",
        f"{base} 怎么改",
    ]
    if parents:
        parent = parents[-1]
        variants.extend(
            [
                f"{parent} {base}",
                f"{doc} {parent} {base}",
            ]
        )
    variants.extend(special_question_variants(section, base))
    return dedupe([clean_query(q) for q in variants if clean_query(q)])


def special_question_variants(section: dict, base: str) -> list[str]:
    doc = section["doc"]
    title = section["title"]
    body = "\n".join(section["body"])
    variants: list[str] = []

    if "胜利条件" in body:
        variants.extend([f"{base} 胜利条件", f"{doc} {base} 胜利条件"])
    if "掉落" in body:
        variants.extend([f"{base} 掉落什么", f"{doc} {base} 掉落什么"])
    if "配方" in body or "制作" in body:
        variants.extend([f"{base} 配方", f"{base} 怎么做", f"{doc} {base} 配方"])
    if "shift+R" in body or "Shift+R" in body:
        variants.extend([f"{base} shift+r", f"{doc} {base} shift+r"])
    if "shift+T" in body or "Shift+T" in body:
        variants.extend([f"{base} shift+t", f"{doc} {base} shift+t"])
    if "禁止附身" in body or "禁止被作祟附身" in body:
        variants.extend([f"{base} 禁止附身什么", f"{doc} {base} 禁止附身什么"])
    if "更新" in title:
        variants.extend([f"{base} 改了什么", f"{doc} {base} 改了什么"])

    if doc == "黎明杀饥模式":
        if title == "人类方规则":
            variants.extend(["黎明杀饥人类怎么赢", "黎明杀饥人类胜利条件", "人类方怎么赢"])
        elif title == "鬼方规则":
            variants.extend(["黎明杀饥鬼方怎么赢", "黎明杀饥鬼方胜利条件", "鬼方怎么赢"])
        elif title == "鬼方详细约束与特权规则":
            variants.extend(
                [
                    "黎明杀饥鬼方禁止附身什么",
                    "黎明杀饥哪些不能附身",
                    "黎明杀饥shift+T怎么用",
                    "黎明杀饥鬼方第几天能召唤boss",
                    "黎明杀饥潜伏梦魇什么时候能用",
                    "黎明杀饥鬼方点数怎么算",
                ]
            )
        elif title == "模组骰子基础设置":
            variants.extend(["黎明杀饥骰子怎么用", "黎明杀饥骰子冷却多久"])

    if doc == "100档规则":
        if any("主流玩法" in parent for parent in section["parents"]):
            variants.extend(
                [
                    f"{title} 主流玩法",
                    f"{title}主流玩法",
                    f"{title} 怎么玩",
                    f"{title}怎么玩",
                    f"100档{title}主流玩法",
                    f"100档{title}怎么玩",
                ]
            )
        if title == "远古铁巨人":
            variants.extend(["100档铁巨掉落什么", "100档铁巨人掉落什么", "远古铁巨人掉落什么"])

    return variants


def clean_query(query: str) -> str:
    query = re.sub(r"\s+", " ", query).strip()
    return query[:120]


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_entries() -> list[dict]:
    entries: list[dict] = []
    for source in SOURCES:
        for section in iter_sections(source):
            chunks = chunk_lines(section["body"])
            for index, chunk in enumerate(chunks, start=1):
                part = index if len(chunks) > 1 else None
                context = compact_context(section)
                answer = f"【{context}】\n" + "\n".join(chunk)
                for question in question_variants(section, part):
                    entries.append({"question": question, "answer": answer})
    return entries


def load_existing_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not KB_PATH.exists():
        return keys
    with KB_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            keys.add((item.get("question", ""), item.get("answer", "")))
    return keys


def main() -> None:
    existing = load_existing_keys()
    entries = []
    for entry in build_entries():
        key = (entry["question"], entry["answer"])
        if key not in existing:
            existing.add(key)
            entries.append(entry)

    with KB_PATH.open("a", encoding="utf-8", newline="\n") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"added={len(entries)}")


if __name__ == "__main__":
    main()
