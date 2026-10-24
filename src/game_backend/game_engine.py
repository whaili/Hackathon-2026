"""Deterministic rules for the first playable Don't Let It Hear scenario."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


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
    mode = "duo"
    mode_title = "双人协作原型"
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
            "mode": self.mode,
            "mode_title": self.mode_title,
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


class GameEngine(Protocol):
    """The room only depends on this contract, never on a specific scenario."""

    phase: str

    def public_state(self, now: float | None = None) -> dict[str, Any]: ...

    def start(self, now: float | None = None) -> dict[str, Any]: ...

    def tick(self, now: float | None = None) -> dict[str, Any] | None: ...

    def process_utterance(self, player_id: str, text: str, source: str = "stt") -> list[dict[str, Any]]: ...


SOLO_STAGES = (
    {
        "name": "识别能源",
        "objective": "听辨容器的脉冲，找出稳定的高频能源。",
        "clue": "三个容器正在发声：低沉的断续声、中频的杂讯，以及稳定而尖锐的脉冲。",
        "success": "稳定脉冲接入能源回路，控制台恢复供电。",
        "forbidden": ("数字", "方向"),
        "terms": ("第一", "第二", "第三", "一号", "二号", "三号", "数字", "左", "右", "方向"),
    },
    {
        "name": "校准频率",
        "objective": "让控制台匹配刚才的稳定脉冲。",
        "clue": "控制台等待一个节奏特征。稳定脉冲始终等距重复，其他两组并不规律。",
        "success": "频率锁定，舱门的锁定机构开始松开。",
        "forbidden": ("颜色", "开关"),
        "terms": ("颜色", "红", "蓝", "绿", "黄", "开关", "按钮"),
    },
    {
        "name": "解除并点火",
        "objective": "先解除舱门锁定，再启动逃生舱。",
        "clue": "舱门仍被安全锁扣固定。锁扣解除后，主推进才会响应。",
        "success": "逃生舱正在点火。",
        "forbidden": ("舱门", "出口"),
        "terms": ("舱门", "门", "出口"),
    },
)


@dataclass
class SoloChallengeState:
    """Voice-only, deterministic three-stage solo challenge.

    Intent recognition remains deliberately bounded: natural phrasings map into
    a small, testable set of scenario actions before a state transition occurs.
    """

    mode: str = "solo"
    mode_title: str = "单人挑战 · 静默协议"
    phase: str = "lobby"
    alert_level: int = 0
    duration_seconds: int = GAME_DURATION_SECONDS
    started_at: float | None = None
    ended_remaining_time: int | None = None
    stage_index: int = 0
    clue_revealed: bool = False
    door_unlocked: bool = False
    help_remaining: int = 2
    error_count: int = 0
    last_consequence: str = "选择单人挑战后，系统会用语音引导你逃离实验室。"

    def remaining_time(self, now: float | None = None) -> int:
        if self.phase != "active" or self.started_at is None:
            return self.duration_seconds if self.phase == "lobby" else self.ended_remaining_time or 0
        current_time = time.time() if now is None else now
        return max(0, self.duration_seconds - max(0, int(current_time - self.started_at)))

    @property
    def stage(self) -> dict[str, Any] | None:
        return SOLO_STAGES[self.stage_index] if self.stage_index < len(SOLO_STAGES) else None

    @property
    def forbidden_words(self) -> tuple[str, str]:
        return tuple(self.stage["forbidden"]) if self.stage else ("--", "--")

    def public_state(self, now: float | None = None) -> dict[str, Any]:
        stage = self.stage
        completed = [item["name"] for item in SOLO_STAGES[:self.stage_index]]
        return {
            "mode": self.mode,
            "mode_title": self.mode_title,
            "phase": self.phase,
            "objective": stage["objective"] if stage else "逃离静音实验室",
            "alert_level": self.alert_level,
            "max_alert_level": MAX_ALERT,
            "remaining_time": self.remaining_time(now),
            "forbidden_words": list(self.forbidden_words),
            "completed_items": completed,
            "next_item": stage["name"] if stage else None,
            "stage": self.stage_index + 1 if stage else len(SOLO_STAGES),
            "stage_count": len(SOLO_STAGES),
            "help_remaining": self.help_remaining,
            "clue_revealed": self.clue_revealed,
            "door_unlocked": self.door_unlocked,
            "error_count": self.error_count,
            "last_consequence": self.last_consequence,
            "voice_examples": self._examples(),
        }

    def start(self, now: float | None = None) -> dict[str, Any]:
        self.phase = "active"
        self.alert_level = 0
        self.started_at = now if now is not None else time.time()
        self.ended_remaining_time = None
        self.stage_index = 0
        self.clue_revealed = False
        self.door_unlocked = False
        self.help_remaining = 2
        self.error_count = 0
        self.last_consequence = "静音协议已启动。先用语音探索能源区；监听者已经醒来。"
        return self._event("game_started", consequence=self.last_consequence, narration=self.last_consequence)

    def tick(self, now: float | None = None) -> dict[str, Any] | None:
        if self.phase == "active" and self.remaining_time(now) == 0:
            self.phase = "lost"
            self.ended_remaining_time = 0
            self.last_consequence = "倒计时归零，实验室被监听者封锁。"
            return self._event("game_lost", reason="timeout", consequence=self.last_consequence)
        return None

    def process_utterance(self, player_id: str, text: str, source: str = "stt") -> list[dict[str, Any]]:
        text = text.strip()[:200]
        if not text:
            return []
        events = [self._event("transcript", player_id=player_id, text=text, source=source)]
        timeout = self.tick()
        if timeout:
            return events + [timeout]
        if self.phase != "active" or self.stage is None:
            return events

        hits = [term for term in self.stage["terms"] if term in text]
        if hits:
            self.error_count += 1
            events.append(self._raise_alert(player_id, "forbidden_concept", f"监听者捕捉到了禁忌表达：{hits[0]}。"))
            return events

        compact = normalize(text)
        if any(word in compact for word in ("提示", "帮助", "求助", "告诉我", "帮我")):
            events.extend(self._request_help(player_id, source))
        elif any(word in compact for word in ("检查", "探索", "观察", "听", "什么", "哪里", "线索", "看看")):
            self.clue_revealed = True
            self.last_consequence = self.stage["clue"]
            events.append(self._event(
                "clue_revealed", player_id=player_id, stage=self.stage_index + 1,
                consequence=self.last_consequence, narration=self.last_consequence, source=source,
            ))
        else:
            events.extend(self._apply_intent(player_id, compact, source))
        return events

    def _request_help(self, player_id: str, source: str) -> list[dict[str, Any]]:
        if self.help_remaining <= 0:
            self.last_consequence = "求助频道已经耗尽。请根据现有线索继续判断。"
            return [self._event("help_unavailable", player_id=player_id, consequence=self.last_consequence, source=source)]
        self.help_remaining -= 1
        self.clue_revealed = True
        self.error_count += 1
        alert = self._raise_alert(player_id, "help_signal", "求助信号暴露了你的位置。")
        if self.phase != "active":
            return [alert]
        hint = self._event(
            "help_used", player_id=player_id, stage=self.stage_index + 1, remaining=self.help_remaining,
            consequence=self.stage["clue"], narration=self.stage["clue"], source=source,
        )
        return [alert, hint]

    def _apply_intent(self, player_id: str, text: str, source: str) -> list[dict[str, Any]]:
        if self.stage_index == 0:
            if any(word in text for word in ("高", "尖", "刺耳", "稳定")):
                if not self.clue_revealed:
                    return [self._need_clue(player_id, source)]
                return self._complete_stage(player_id, source)
            if any(word in text for word in ("低", "中", "杂")):
                return [self._mistake(player_id, "wrong_energy", "能源接入了不稳定的信号。")]
        elif self.stage_index == 1:
            if any(word in text for word in ("稳定", "等距", "重复", "匹配", "校准")):
                if not self.clue_revealed:
                    return [self._need_clue(player_id, source)]
                return self._complete_stage(player_id, source)
            if any(word in text for word in ("杂", "断续", "随机")):
                return [self._mistake(player_id, "wrong_frequency", "控制台拒绝了不规则的频率。")]
        elif self.stage_index == 2:
            if not self.door_unlocked and any(word in text for word in ("解除", "解锁", "松开", "锁扣")):
                self.door_unlocked = True
                self.last_consequence = "锁扣解除，主推进已经可以响应。现在用语音请求启动。"
                return [self._event(
                    "subsystem_unlocked", player_id=player_id, consequence=self.last_consequence,
                    narration=self.last_consequence, source=source,
                )]
            if self.door_unlocked and any(word in text for word in ("点火", "启动", "推进", "发射")):
                return self._complete_stage(player_id, source)
            if not self.door_unlocked and any(word in text for word in ("点火", "启动", "推进", "发射")):
                return [self._mistake(player_id, "sequence_error", "安全锁扣还没有解除，推进请求被拒绝。")]
        self.last_consequence = "系统无法确认你的意图。可以探索、请求提示，或用特征描述要操作的目标。"
        return [self._event(
            "clarification_needed", player_id=player_id, consequence=self.last_consequence,
            narration=self.last_consequence, source=source,
        )]

    def _need_clue(self, player_id: str, source: str) -> dict[str, Any]:
        self.last_consequence = "系统需要先确认环境线索。请先说“探索”或“检查”，再描述你的选择。"
        return self._event(
            "clarification_needed", player_id=player_id, consequence=self.last_consequence,
            narration=self.last_consequence, source=source,
        )

    def _complete_stage(self, player_id: str, source: str) -> list[dict[str, Any]]:
        completed = self.stage
        assert completed is not None
        self.stage_index += 1
        self.clue_revealed = False
        if self.stage_index == len(SOLO_STAGES):
            self.ended_remaining_time = self.remaining_time()
            self.phase = "won"
            self.last_consequence = "推进器点火成功。你在监听者锁定前逃离了实验室。"
            return [self._event(
                "game_won", player_id=player_id, stage=completed["name"], consequence=self.last_consequence,
                narration=self.last_consequence, source=source,
            )]
        self.last_consequence = f"{completed['success']} 监听者换了一条新的语言限制。"
        return [self._event(
            "stage_completed", player_id=player_id, stage=completed["name"], consequence=self.last_consequence,
            narration=self.last_consequence, source=source,
        )]

    def _mistake(self, player_id: str, reason: str, detail: str) -> dict[str, Any]:
        self.error_count += 1
        return self._raise_alert(player_id, reason, detail)

    def _raise_alert(self, player_id: str, reason: str, detail: str) -> dict[str, Any]:
        self.alert_level = min(MAX_ALERT, self.alert_level + 1)
        consequence = COMPLICATIONS[(self.error_count + self.alert_level - 1) % len(COMPLICATIONS)]
        self.last_consequence = f"{detail} {consequence}"
        event_type = "alert_raised"
        if self.alert_level >= MAX_ALERT:
            self.phase = "lost"
            self.ended_remaining_time = self.remaining_time()
            self.last_consequence += " 警报满格，监听者已经定位你。"
            event_type = "game_lost"
        return self._event(event_type, player_id=player_id, reason=reason, consequence=self.last_consequence)

    def _examples(self) -> list[str]:
        if self.phase != "active" or self.stage is None:
            return ["说“探索能源区”开始获取线索"]
        if self.stage_index == 0:
            return ["说“探索能源区”", "说“选择最尖锐的脉冲”"]
        if self.stage_index == 1:
            return ["说“检查控制台”", "说“校准稳定重复的频率”"]
        if not self.door_unlocked:
            return ["说“解除安全锁扣”"]
        return ["说“启动主推进”"]

    def _event(self, event_type: str, **data: Any) -> dict[str, Any]:
        return {"type": event_type, "at": time.time(), **data}


def create_game(mode: str) -> GameEngine:
    if mode == "solo":
        return SoloChallengeState()
    if mode == "duo":
        return GameState()
    raise ValueError(f"Unsupported game mode: {mode}")
