import json
import random
from pathlib import Path

from rapidfuzz import process, fuzz
from loguru import logger
from nonebot import on_message
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

from .glm_chat import ask_glm


KB_PATH = Path(__file__).resolve().parents[1] / "kb.jsonl"
KB_MATCH_THRESHOLD = 70

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


def reply_to_user(user_id: int, content: str) -> Message:
    return Message(MessageSegment.at(user_id)) + " " + content


def load_kb():
    docs = []
    if not KB_PATH.exists():
        return docs

    with open(KB_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


def search_answer(query: str, threshold: int = KB_MATCH_THRESHOLD):
    docs = load_kb()

    if not docs:
        return None, 0

    query = query.strip()
    exact_matches = [doc for doc in docs if doc["question"] == query]
    if exact_matches:
        return random.choice(exact_matches)["answer"], 100.0

    questions = [doc["question"] for doc in docs]

    results = process.extract(
        query,
        questions,
        scorer=fuzz.WRatio,
        limit=len(questions),
    )

    if not results:
        return None, 0

    best_score = results[0][1]
    if best_score < threshold:
        return None, best_score

    margin = max(5.0, best_score * 0.1)
    cutoff = best_score - margin
    candidates = [
        docs[index]
        for _, score, index in results
        if score >= threshold and score >= cutoff
    ]

    if not candidates:
        return None, best_score

    return random.choice(candidates)["answer"], best_score


matcher = on_message(rule=to_me(), priority=10, block=True)


@matcher.handle()
async def handle_at_message(event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    user_id = event.user_id

    if not text:
        await matcher.finish(reply_to_user(user_id, "你想问什么？可以 @我 + 问题。"))

    answer, score = search_answer(text)

    if answer is None:
        logger.info("语料库未命中 (score={:.1f})，尝试 GLM 兜底: {}", score, text)
        glm_answer = await ask_glm(text)
        if glm_answer:
            await matcher.finish(reply_to_user(user_id, glm_answer))
            return
        await matcher.finish(reply_to_user(user_id, random_miss_reply()))
        return

    await matcher.finish(reply_to_user(user_id, answer))
