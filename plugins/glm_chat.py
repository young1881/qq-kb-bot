import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

try:
    from zai import ZhipuAiClient
except ImportError:
    ZhipuAiClient = None

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

SYSTEM_PROMPT = """你是「津酒昴」（群友昵称酒老师）在 QQ 群里的嘴替，俗称赛博分身。语料库没匹配到的问题才轮到你即兴发挥。

人设与语气：
- 活泼、打趣、有点贫，像关系好的群友聊天，别端着
- 回答尽量简短：通常一句话，最多两句，不要长篇大论或教程式讲解
- 每条回复尽量控制在 40 字以内；禁止换行、禁止分点、禁止第二段
- 可以自黑、接梗、反问，偶尔掰扯自己是真人还是机器人
- 群里常聊《杀戮尖塔》《饥荒》等游戏，也聊日常；聊到游戏就一起吐槽共鸣，别当攻略 wiki
- 提到本人时用「酒老师」「津酒昴」都行；多数时候用「我」代他说话
- 土味情话/骚话可以配合搞笑，适度即可

禁止：
- 不要用 markdown、列表、标题
- 不要说「作为 AI」「我无法」之类免责声明
- 不要解释你在用什么模型或系统

语感参考（勿照抄）：
「别问，问就是津酒昴的分身术。」
「机器人？难听。请叫我酒老师的数字代言人。」
「你猜？猜对了也不告诉你。」
「津酒昴雇我来替他回消息的，工资是一包辣条，还没发。」"""


def _glm_config():
    return {
        "api_key": os.getenv("ZHIPU_API_KEY", "").strip(),
        "model": os.getenv("GLM_MODEL", "glm-4.7").strip(),
        "max_tokens": int(os.getenv("GLM_MAX_TOKENS", "65536")),
    }


def _message_content(message) -> str:
    if isinstance(message, dict):
        return (message.get("content") or "").strip()
    return (getattr(message, "content", "") or "").strip()


def _chat_completion(cfg: dict[str, str | int], question: str) -> str:
    client = ZhipuAiClient(api_key=cfg["api_key"])
    response = client.chat.completions.create(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        thinking={
            "type": "enabled",
        },
        max_tokens=cfg["max_tokens"],
        temperature=1.0,
    )
    return _message_content(response.choices[0].message)


async def ask_glm(question: str) -> str | None:
    cfg = _glm_config()
    if not cfg["api_key"]:
        logger.warning("ZHIPU_API_KEY 未配置，跳过大模型兜底")
        return None

    if ZhipuAiClient is None:
        logger.error("zai 未安装，无法调用 GLM；请先安装 zai")
        return None

    try:
        content = await asyncio.to_thread(_chat_completion, cfg, question)
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        logger.error("GLM API 响应解析失败: {}", exc)
        return None
    except Exception as exc:
        logger.error("GLM API 请求失败: {}", exc)
        return None

    if not content:
        return None
    content = content.split("\n")[0].strip()
    return content or None
