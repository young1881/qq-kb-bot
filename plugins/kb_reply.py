import json
import random
from pathlib import Path

from rapidfuzz import process, fuzz
from nonebot import on_message
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message


KB_PATH = Path(__file__).resolve().parents[1] / "kb.jsonl"


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


def search_answer(query: str, threshold: int = 60):
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

    if not text:
        await matcher.finish("你想问什么？可以 @我 + 问题。")

    answer, score = search_answer(text)

    if answer is None:
        await matcher.finish("这个问题我还没有收录到语料库里。")

    await matcher.finish(Message(answer))