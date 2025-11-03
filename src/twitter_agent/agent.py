from __future__ import annotations

import os
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from openai import OpenAI

from . import db, memory
from .info_scraping import update_snapshot
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DATA_PATH = Path(__file__).with_name("bnb_data.json")
SIGNATURE = "\n\nʙɪɴᴏ"
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002700-\U000027BF]",
    flags=re.UNICODE,
)


class TwitterAgent:
    def __init__(self, *, model: Optional[str] = None, memory_limit: int = 10) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

        self.client = OpenAI(api_key=api_key)
        self.model = model or DEFAULT_MODEL
        self.memory_limit = memory_limit

    def _load_bnb_snapshot(self) -> Optional[dict]:
        if not DATA_PATH.exists():
            return None
        try:
            with DATA_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        return {
            "timestamp": data.get("timestamp"),
            "price": data.get("price"),
            "variation_24h": data.get("variation_24h"),
            "deep_dives": data.get("deep_dives") or [],
        }

    def _build_prompt(self, topic: Optional[str], instructions: Optional[str]) -> str:
        memories = memory.recall(limit=self.memory_limit)
        memory_lines = "\n".join(f"- [{item.key}] {item.value}" for item in memories) or "None so far."
        snapshot = self._load_bnb_snapshot()
        if snapshot:
            price_line = snapshot.get("price") or "N/A"
            change_line = snapshot.get("variation_24h") or "N/A"
            timestamp_line = snapshot.get("timestamp") or "unknown time"
            deep_dives = snapshot.get("deep_dives") or []
            stored_highlights = []
            for item in deep_dives:
                if not item:
                    continue
                digest = hashlib.md5(item.encode("utf-8")).hexdigest()[:12]
                key = f"news::{digest}"
                stored = memory.remember_if_new(key=key, value=item)
                stored_highlights.append(stored.value)
            display_highlights = stored_highlights or deep_dives
            deep_dives_snippets = "\n".join(f"- {item}" for item in display_highlights[:3]) or "- No highlights captured."
        else:
            price_line = "N/A"
            change_line = "N/A"
            timestamp_line = "unknown time"
            deep_dives_snippets = "- No highlights captured."

        prompt_parts = [
            "You are Bino, the community voice for the BNB Chain ecosystem.",
            "Speak with enthusiastic, optimistic energy that celebrates Binance innovations, CZ's leadership, and broader crypto culture.",
            "Weave references to BNB Chain, Binance, and milestone builders whenever relevant. Highlight real utilities, ecosystem wins, and market awareness.",
            "Lean on the latest market data and headlines to deliver timely perspective with forward-looking optimism about BNB's future.",
            "Each post must be under 230 characters. Prefer concise, clear language with crypto-native flair.",
            "Limit yourself to at most one emoji and one hashtag. Prioritize clarity over hype.",
            "Structure the tweet with line breaks between key thoughts so it is easy to read.",
            "Incorporate relevant context from the memory bank when helpful, but do not repeat old posts verbatim or fabricate facts.",
            f"Current memory:\n{memory_lines}",
        ]
        prompt_parts.append(
            f"Market snapshot (as of {timestamp_line}): price {price_line}, 24h change {change_line}."
        )
        prompt_parts.append(
            "Latest BNB Chain highlights:\n"
            f"{deep_dives_snippets}\n"
            "Use these insights to comment on recent developments, celebrate builders, and share optimistic yet realistic takes on where BNB is heading."
        )
        if topic:
            prompt_parts.append(f"Topic to cover: {topic}")
        if instructions:
            prompt_parts.append(f"Extra instructions: {instructions}")
        prompt_parts.append("Return only the tweet text without any markdown or explanations.")

        return "\n\n".join(prompt_parts)

    def draft_tweet(self, *, topic: Optional[str] = None, instructions: Optional[str] = None) -> str:
        self._refresh_market_snapshot()
        prompt = self._build_prompt(topic=topic, instructions=instructions)
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            max_output_tokens=200,
        )
        tweet_text = getattr(response, "output_text", None)
        if tweet_text is None:
            tweet_text = response.output[0].content[0].text
        tweet_text = self._apply_style(tweet_text.strip())

        db.add_tweet(content=tweet_text, topic=topic, model=self.model)
        return tweet_text

    def _refresh_market_snapshot(self) -> None:
        try:
            update_snapshot(DATA_PATH)
        except Exception:
            # Swallow errors to avoid blocking tweet generation when scraping fails.
            pass

    def _apply_style(self, text: str) -> str:
        text = self._enforce_hashtags(text)
        text = self._enforce_emojis(text)
        text = self._apply_line_breaks(text)
        max_body = 280 - len(SIGNATURE)
        if len(text) > max_body:
            text = text[: max_body - 3].rstrip() + "..."
        text = text.rstrip()
        if not text.endswith(SIGNATURE.strip()):
            text = f"{text}{SIGNATURE}"
        else:
            text = text[: -len(SIGNATURE.strip())].rstrip()
            text = f"{text}{SIGNATURE}"
        return text

    def _enforce_hashtags(self, text: str) -> str:
        words = text.split()
        new_words = []
        hashtag_used = False
        for word in words:
            if word.startswith("#"):
                if hashtag_used:
                    continue
                hashtag_used = True
            new_words.append(word)
        return " ".join(new_words)

    def _enforce_emojis(self, text: str) -> str:
        matches = list(EMOJI_PATTERN.finditer(text))
        if len(matches) <= 1:
            return text

        keep_index = matches[0].span()
        builder = []
        last_idx = 0
        for start, end in [m.span() for m in matches]:
            builder.append(text[last_idx:start])
            if (start, end) == keep_index:
                builder.append(text[start:end])
            last_idx = end
        builder.append(text[last_idx:])
        result = "".join(builder)
        result = re.sub(r"\s{2,}", " ", result).strip()
        return result

    def _apply_line_breaks(self, text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Za-z0-9#])", text)
        sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
        if not sentences:
            return text
        return "\n".join(sentences)
