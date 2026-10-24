"""Deterministic rules for the first playable Don't Let It Hear scenario."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any


MAX_ALERT = 5
GAME_DURATION_SECONDS = 90
ITEMS = ("钥匙", "电池", "样本")
FORBIDDEN_ROUNDS = (("左", "右"), ("快", "慢"), ("门", "出口"), ("声音", "安静"))
COMPLICATIONS = (
    "机械臂误碰控制台，警报升高。",
    "逃生舱的指示灯熄灭了一盏。",
    "怪物循着声音靠近了。",
    "舱门锁扣被卡住，必须更小心地继续。",
)


def normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?:：；;\-]", "", text).lower()


@dataclass
class GameState:
    phase: str = "lobby"
    alert_level: int = 0
    duration_seconds: int = GAME_DURATION_SECONDS
    started_at: float | None = None
    ended_remaining_time: int | None = None
    completed_items: list[str] = field(default_factory=list)
    held_items: dict[str, str] = field(default_factory=dict)
    item_locations: dict[str, str] = field(default_factory=lambda: {item: "实验室" for item in ITEMS})
    error_count: int = 0
    last_consequence: str = "等待两名玩家开始。"

    def remaining_time(self, now: float | None = None) -> int:
        if self.phase != "active" or self.started_at is None:
            if self.phase == "lobby":
                return self.duration_seconds
            return self.ended_remaining_time or 0
        current_time = time.time() if now is None else now
        elapsed = max(0, int(current_time - self.started_at))
        return max(0, self.duration_seconds - elapsed)

    @property
    def next_item(self) -> str | None:
        return ITEMS[len(self.completed_items)] if len(self.completed_items) < len(ITEMS) else None

    @property
    def forbidden_words(self) -> tuple[str, str]:
        # Both successful progress and mistakes change the language pressure.
        return FORBIDDEN_ROUNDS[(len(self.completed_items) + self.error_count) % len(FORBIDDEN_ROUNDS)]

    def public_state(self, now: float | None = None) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "objective": "依次将钥匙、电池、样本放入逃生舱",
            "alert_level": self.alert_level,
            "max_alert_level": MAX_ALERT,
            "remaining_time": self.remaining_time(now),
            "forbidden_words": list(self.forbidden_words),
            "completed_items": self.completed_items.copy(),
            "next_item": self.next_item,
            "held_items": self.held_items.copy(),
            "item_locations": self.item_locations.copy(),
            "error_count": self.error_count,
            "last_consequence": self.last_consequence,
        }

    def start(self, now: float | None = None) -> dict[str, Any]:
        self.phase = "active"
        self.alert_level = 0
        self.started_at = now if now is not None else time.time()
        self.ended_remaining_time = None
        self.completed_items.clear()
        self.held_items.clear()
        self.item_locations = {item: "实验室" for item in ITEMS}
        self.error_count = 0
        self.last_consequence = "逃生舱已解锁。怪物正在监听你们的对话。"
        return self._event("game_started", consequence=self.last_consequence)

    def tick(self, now: float | None = None) -> dict[str, Any] | None:
        if self.phase == "active" and self.remaining_time(now) == 0:
            self.phase = "lost"
            self.ended_remaining_time = 0
            self.last_consequence = "倒计时归零，逃生舱自动封闭。"
            return self._event("game_lost", reason="timeout", consequence=self.last_consequence)
        return None

    def process_utterance(self, player_id: str, text: str, source: str = "stt") -> list[dict[str, Any]]:
        text = text.strip()[:200]
        if not text:
            return []
        events = [self._event("transcript", player_id=player_id, text=text, source=source)]
        timeout = self.tick()
        if timeout:
            events.append(timeout)
            return events
        if self.phase != "active":
            return events

        hits = [word for word in self.forbidden_words if word in text]
        if hits:
            self.error_count += 1
            events.append(self._raise_alert(player_id, "forbidden_word", "、".join(hits)))
            if self.phase != "active":
                return events
        action = self._parse_action(text)
        if action:
            events.extend(self._apply_action(player_id, action, source))
        return events

    def _parse_action(self, text: str) -> tuple[str, str | None] | None:
        compact = normalize(text)
        item = next((candidate for candidate in ITEMS if candidate in compact), None)
        if any(verb in compact for verb in ("拿", "拾", "取", "捡")) and item:
            return "pick", item
        if any(verb in compact for verb in ("放入", "放进", "装入", "塞进", "投入")) and ("逃生舱" in compact or "舱" in compact):
            return "place", None
        if "移动" in compact or "前往" in compact:
            return "move", None
        return None

    def _apply_action(self, player_id: str, action: tuple[str, str | None], source: str) -> list[dict[str, Any]]:
        kind, item = action
        if kind == "move":
            self.last_consequence = "你们调整了站位，机械臂等待下一条指令。"
            return [self._event("action_applied", player_id=player_id, action="move", source=source,
                                consequence=self.last_consequence)]
        if kind == "pick":
            return self._pick(player_id, item or "", source)
        return self._place(player_id, source)

    def _pick(self, player_id: str, item: str, source: str) -> list[dict[str, Any]]:
        if self.held_items.get(player_id):
            return [self._mistake(player_id, "hands_full", "机械臂已经拿着物品，却又收到拾取指令。")]
        if item != self.next_item:
            expected = self.next_item or "无"
            return [self._mistake(player_id, "wrong_item", f"机械臂把目标听成了{item}，当前应处理{expected}。")]
        if self.item_locations[item] != "实验室":
            return [self._mistake(player_id, "item_unavailable", f"{item} 已经不在实验室里。")]
        self.held_items[player_id] = item
        self.item_locations[item] = f"{player_id} 手中"
        self.last_consequence = f"{player_id} 拿起了{item}，现在要把它放入逃生舱。"
        return [self._event("action_applied", player_id=player_id, action="pick", item=item, source=source,
                            consequence=self.last_consequence)]

    def _place(self, player_id: str, source: str) -> list[dict[str, Any]]:
        item = self.held_items.get(player_id)
        if not item:
            return [self._mistake(player_id, "empty_hands", "机械臂把空手伸进了逃生舱。")]
        if item != self.next_item:
            return [self._mistake(player_id, "wrong_placement", f"{item} 被放在错误的时机，逃生舱拒绝接收。")]
        previous_words = list(self.forbidden_words)
        del self.held_items[player_id]
        self.item_locations[item] = "逃生舱"
        self.completed_items.append(item)
        if self.next_item is None:
            self.ended_remaining_time = self.remaining_time()
            self.phase = "won"
            self.last_consequence = "逃生舱点火成功，你们逃离了实验室。"
            return [self._event("game_won", player_id=player_id, action="place", item=item, source=source,
                                consequence=self.last_consequence)]
        self.last_consequence = f"{item} 已放入逃生舱。怪物换了一组新的禁语。"
        return [self._event("action_applied", player_id=player_id, action="place", item=item, source=source,
                            previous_forbidden_words=previous_words, consequence=self.last_consequence)]

    def _mistake(self, player_id: str, reason: str, consequence: str) -> dict[str, Any]:
        self.error_count += 1
        return self._raise_alert(player_id, reason, consequence)

    def _raise_alert(self, player_id: str, reason: str, detail: str) -> dict[str, Any]:
        self.alert_level = min(MAX_ALERT, self.alert_level + 1)
        consequence = COMPLICATIONS[(self.error_count + self.alert_level - 1) % len(COMPLICATIONS)]
        self.last_consequence = f"{detail} {consequence}"
        event_type = "alert_raised"
        if self.alert_level >= MAX_ALERT:
            self.phase = "lost"
            self.last_consequence += " 警报满格，怪物发现了你们。"
            event_type = "game_lost"
        return self._event(event_type, player_id=player_id, reason=reason, consequence=self.last_consequence)

    def _event(self, event_type: str, **data: Any) -> dict[str, Any]:
        return {"type": event_type, "at": time.time(), **data}
