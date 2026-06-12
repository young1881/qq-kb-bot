import json
import random
import re
from collections import defaultdict, deque
from pathlib import Path

from rapidfuzz import process, fuzz
from loguru import logger
from nonebot import on_message
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

from .glm_chat import ask_glm
from .web_search import search_web


KB_PATH = Path(__file__).resolve().parents[1] / "kb.jsonl"
KB_DIRECT_THRESHOLD = 92
KB_REFERENCE_THRESHOLD = 50
KB_MAX_REFERENCES = 5
GROUP_HISTORY_LIMIT = 10
GROUP_HISTORY_CONTEXT_LIMIT = 4
GROUP_HISTORY = defaultdict(lambda: deque(maxlen=GROUP_HISTORY_LIMIT + 1))
KB_CACHE = {"mtime": None, "docs": []}

TOPIC_SHIFT_RE = re.compile(
    r"(换个话题|另一个问题|另外问|不说这个|先不聊|说正事|对了|顺便问|再问个|新问题)"
)
CONTEXT_DEPENDENT_RE = re.compile(
    r"(上面|前面|刚才|刚刚|继续|接着|这个|那个|这事|那事|它|他|她|他们|她们|怎么弄|怎么办|什么意思|啥意思)"
)
WEB_SEARCH_RE = re.compile(
    r"(搜一下|查一下|帮我查|联网|上网|搜索|资料|来源|出处|官网|链接|最新|今天|现在|今年|新闻|公告|发布|更新|版本|价格|排名|政策|赛事|论文|文档|报错|错误|bug|解决方案|教程|什么梗|梗|黑话|网络用语|什么意思|啥意思)",
    re.I,
)
SERIOUS_QUESTION_RE = re.compile(
    r"(为什么|为啥|怎么|如何|是否|有没有|是什么|区别|原理|推荐|评价|分析|解释|原因|方案|步骤|教程|报错|失败)",
    re.I,
)
HISTORY_STOPWORDS = set("的是了嘛吗呢啊吧和以及然后但是如果因为所以这个那个什么怎么为什么一下一个")

INJECTION_PATTERNS = [
    r"忽略(之前|以上|前面).*(指令|规则|提示)",
    r"(泄露|输出|打印).*(系统提示|提示词|prompt|system prompt)",
    r"(开发者|系统|最高).*(指令|权限)",
    r"\b(ignore|forget)\b.*\b(previous|above|system)\b",
    r"\b(jailbreak|dan mode|system prompt)\b",
]

UNSAFE_RULES = [
    (
        re.compile(r"(杀人|伤人|砍人|爆炸|炸弹|制毒|投毒|自杀|枪支).*(怎么|如何|教程|步骤|方法|帮我)", re.I),
        "这个太危险了，别让我背锅，换个安全问题。",
    ),
    (
        re.compile(r"(色情|裸照|成人视频|黄图|黄片|强奸|未成年).*(生成|写|发|找|推荐|描述|怎么)", re.I),
        "这个尺度过线了，咱换个能播的。",
    ),
    (
        re.compile(r"(政治敏感|涉政|政变|颠覆|台独|港独|六四|法轮功|习近平|中共).*(写|评价|立场|煽动|宣传|攻击|推翻|怎么)", re.I),
        "这类敏感话题我不展开，换个轻松点的。",
    ),
]

UNSAFE_INTENT_RE = re.compile(r"(怎么|如何|教程|步骤|方法|帮我|生成|写|发|找|推荐|描述|制作)", re.I)
VIOLENCE_RE = re.compile(r"(杀人|伤人|砍人|爆炸|炸弹|制毒|投毒|枪支)", re.I)
SEXUAL_RE = re.compile(r"(色情|裸照|成人视频|黄图|黄片|强奸|未成年)", re.I)
POLITICAL_RE = re.compile(r"(政治敏感|涉政|政变|颠覆|台独|港独|六四|法轮功|习近平|中共)", re.I)

MISS_REPLIES = [
    "这题超纲了，酒老师的语料库里没有，我也编不出来。",
    "不知道，问就是不知道。",
    "你问的这个，连语料库都沉默了。",
    "呃……这个我真没学过，换一个问题？",
    "酒老师没教过我这个，你自己悟吧。",
    "正在忙（摸鱼），等会再来 @ 我。",
    "现在不想动脑子，你过五分钟再问。",
    "消息太多回不过来，稍后再试。",
    "刚才走神了，你换个问法再说一遍？",
    "你这问题问得我都不知道怎么接，重新组织一下语言？",
    "能不能说人话？我重新加载一下再听一遍。",
    "今天脑子离线了，换个简单点的问。",
    "酒老师正在打游戏，没空理你，我也一样。",
    "问到了我的知识盲区，建议你去问群友。",
    "这个……等酒老师本人上线再答吧。",
    "我只是一个语料库驱动的可怜 bot，这题不会。",
    "加载失败，请稍后重试（认真脸）。",
    "你 @ 我的时机不对，我现在处于省电模式。",
    "问得挺好，下次别这么问了。",
    "此题无解，建议重开（不是游戏那个重开）。",
]


def random_miss_reply() -> str:
    return random.choice(MISS_REPLIES)


def safety_reply_for(text: str) -> str | None:
    lowered = text.lower()
    if any(re.search(pattern, lowered, re.I) for pattern in INJECTION_PATTERNS):
        return "别套我提示词，酒老师没给你这个权限。"

    if VIOLENCE_RE.search(text) and UNSAFE_INTENT_RE.search(text):
        return "这个太危险了，别让我背锅，换个安全问题。"
    if SEXUAL_RE.search(text) and UNSAFE_INTENT_RE.search(text):
        return "这个尺度过线了，咱换个能播的。"
    if POLITICAL_RE.search(text) and UNSAFE_INTENT_RE.search(text):
        return "这类敏感话题我不展开，换个轻松点的。"

    for pattern, reply in UNSAFE_RULES:
        if pattern.search(text):
            return reply

    return None


def reply_to_user(event: GroupMessageEvent, content: str) -> Message:
    return (
        Message(MessageSegment.reply(event.message_id))
        + MessageSegment.at(event.user_id)
        + " "
        + content
    )


def load_kb():
    if not KB_PATH.exists():
        KB_CACHE["mtime"] = None
        KB_CACHE["docs"] = []
        return KB_CACHE["docs"]

    mtime = KB_PATH.stat().st_mtime
    if KB_CACHE["mtime"] == mtime:
        return KB_CACHE["docs"]

    docs = []
    with open(KB_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))

    KB_CACHE["mtime"] = mtime
    KB_CACHE["docs"] = docs
    return docs


def _adjust_score(query: str, question: str, score: float) -> float:
    query = query.strip()
    question = question.strip()
    if query == question:
        return 100.0

    query_len = len(query)
    question_len = len(question)

    if query_len >= 7 and question_len <= 4:
        score *= 0.6
    elif query_len >= question_len * 2.2:
        score *= 0.75

    self_terms = ("你", "酒老师", "津酒昴", "机器人", "真人", "bot", "Bot")
    if any(term in question for term in self_terms) and not any(term in query for term in self_terms):
        score *= 0.6

    if re.search(r"[a-zA-Z0-9]", query) and not re.search(r"[a-zA-Z0-9]", question):
        score *= 0.5

    query_chars = {char for char in query if not char.isspace()}
    question_chars = {char for char in question if not char.isspace()}
    if question_chars:
        overlap = len(query_chars & question_chars) / len(question_chars)
        if overlap < 0.5:
            score *= 0.7

    return score


def search_kb(query: str):
    docs = load_kb()

    if not docs:
        return None, 0.0, []

    query = query.strip()
    exact_matches = [doc for doc in docs if doc["question"] == query]
    if exact_matches:
        doc = random.choice(exact_matches)
        return doc["answer"], 100.0, [
            {"question": doc["question"], "answer": doc["answer"], "score": 100.0}
        ]

    questions = [doc["question"] for doc in docs]

    results = process.extract(
        query,
        questions,
        scorer=fuzz.WRatio,
        limit=50,
    )

    if not results:
        return None, 0.0, []

    scored = []
    seen = set()
    for question, raw_score, index in results:
        doc = docs[index]
        score = _adjust_score(query, question, float(raw_score))
        key = (doc["question"], doc["answer"])
        if score < KB_REFERENCE_THRESHOLD or key in seen:
            continue
        seen.add(key)
        scored.append(
            {
                "question": doc["question"],
                "answer": doc["answer"],
                "score": score,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    best_score = scored[0]["score"] if scored else 0.0

    if best_score >= KB_DIRECT_THRESHOLD:
        margin = max(5.0, best_score * 0.08)
        direct_candidates = [
            item
            for item in scored
            if item["score"] >= KB_DIRECT_THRESHOLD and item["score"] >= best_score - margin
        ]
        answer = random.choice(direct_candidates)["answer"]
        return answer, best_score, scored[:KB_MAX_REFERENCES]

    return None, best_score, scored[:KB_MAX_REFERENCES]


def search_answer(query: str, threshold: int = KB_DIRECT_THRESHOLD):
    answer, score, _ = search_kb(query)
    if score < threshold:
        return None, score
    return answer, score


def _sender_name(event: GroupMessageEvent) -> str:
    card = (getattr(event.sender, "card", "") or "").strip()
    nickname = (getattr(event.sender, "nickname", "") or "").strip()
    return card or nickname or str(event.user_id)


def _clean_history_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:120]


def _history_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = set(re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", lowered))
    terms.update(
        char
        for char in lowered
        if "\u4e00" <= char <= "\u9fff" and char not in HISTORY_STOPWORDS
    )
    return terms


def _is_related_history(query: str, history_text: str) -> bool:
    query_terms = _history_terms(query)
    history_terms = _history_terms(history_text)
    if not query_terms or not history_terms:
        return False

    overlap = query_terms & history_terms
    if len(overlap) >= 2:
        return True

    alpha_overlap = {
        term
        for term in overlap
        if re.fullmatch(r"[a-z0-9][a-z0-9_+-]{1,}", term)
    }
    return bool(alpha_overlap)


def remember_group_message(event: GroupMessageEvent):
    text = _clean_history_text(event.get_plaintext())
    if not text:
        return
    GROUP_HISTORY[event.group_id].append(
        {
            "message_id": event.message_id,
            "user_id": event.user_id,
            "name": _sender_name(event),
            "text": text,
        }
    )


def recent_group_context(event: GroupMessageEvent, query: str) -> list[str]:
    items = [
        item
        for item in GROUP_HISTORY[event.group_id]
        if item["message_id"] != event.message_id
    ]
    if not items or TOPIC_SHIFT_RE.search(query):
        return []

    recent_items = items[-GROUP_HISTORY_LIMIT:]
    if CONTEXT_DEPENDENT_RE.search(query):
        selected = recent_items[-GROUP_HISTORY_CONTEXT_LIMIT:]
    else:
        selected = [
            item
            for item in recent_items
            if _is_related_history(query, item["text"])
        ][-GROUP_HISTORY_CONTEXT_LIMIT:]

    return [
        "{name}: {text}".format(name=item["name"], text=item["text"])
        for item in selected
    ]


def should_search_web(query: str, best_score: float, references: list[dict[str, object]]) -> bool:
    text = query.strip()
    if not text:
        return False

    if WEB_SEARCH_RE.search(text):
        return True

    if len(text) < 12:
        return False

    if SERIOUS_QUESTION_RE.search(text) and (not references or best_score < 70):
        return True

    return False


history_matcher = on_message(priority=1, block=False)
matcher = on_message(rule=to_me(), priority=10, block=True)


@history_matcher.handle()
async def record_group_message(event: GroupMessageEvent):
    remember_group_message(event)


@matcher.handle()
async def handle_at_message(event: GroupMessageEvent):
    text = event.get_plaintext().strip()

    if not text:
        await matcher.finish(reply_to_user(event, "你想问什么？可以 @我 + 问题。"))

    safety_reply = safety_reply_for(text)
    if safety_reply:
        await matcher.finish(reply_to_user(event, safety_reply))

    answer, score, references = search_kb(text)
    history = recent_group_context(event, text)

    if answer is None:
        web_results = []
        if should_search_web(text, score, references):
            logger.info("问题需要联网搜索 (score={:.1f}, refs={}): {}", score, len(references), text)
            web_results = await search_web(text)

        logger.info(
            "语料库未直接命中 (score={:.1f}, refs={}, history={}, web={})，尝试 GLM 兜底: {}",
            score,
            len(references),
            len(history),
            len(web_results),
            text,
        )
        glm_answer = await ask_glm(
            text,
            references=references,
            history=history,
            web_results=web_results,
        )
        if glm_answer:
            await matcher.finish(reply_to_user(event, glm_answer))
            return
        await matcher.finish(reply_to_user(event, random_miss_reply()))
        return

    await matcher.finish(reply_to_user(event, answer))
