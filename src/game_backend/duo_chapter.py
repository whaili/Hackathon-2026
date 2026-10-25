"""Server-authoritative two-role chapter with per-player clues."""

import secrets
from dataclasses import dataclass, field

from .game_engine import GameState, normalize


SIGNALS = (("低沉脉冲", "厚重回声"), ("尖锐脉冲", "清亮回声"), ("断续脉冲", "停顿回声"))
SYMBOLS = ("星环", "月痕", "潮纹")
SYMBOL_ALIASES = {"星环": ("星环",), "月痕": ("月痕", "月恒", "月衡"),
                  "潮纹": ("潮纹", "潮文", "朝纹", "朝文")}
STAGES = ("接通能源", "辨认伪装", "共同点火")


@dataclass
class DuoChapterState(GameState):
    mode_title = "分离频道 · 免费序章"
    duration_seconds: int = 720
    roles: dict = field(default_factory=dict)
    puzzles: list = field(default_factory=list)
    stage_index: int = 0
    authorized: bool = False
    learned_phrase: str = ""

    def register(self, player):
        if player not in self.roles:
            if len(self.roles) >= 2:
                return False
            self.roles[player] = "现场员" if not self.roles else "监听员"
        return True

    @property
    def forbidden_words(self):
        return ("左", "右") + ((self.learned_phrase,) if self.learned_phrase else ())

    def start(self, now=None):
        event = super().start(now)
        self.stage_index = 0
        self.authorized = False
        self.learned_phrase = ""
        self.puzzles = []
        for _ in STAGES:
            choices = list(SIGNALS)
            secrets.SystemRandom().shuffle(choices)
            self.puzzles.append({"mapping": dict(zip(SYMBOLS, choices)), "target": secrets.choice(SYMBOLS)})
        self.last_consequence = "你们被分隔在两个频道。交换私有线索，由监听员授权，现场员校准。"
        return {**event, "consequence": self.last_consequence}

    def public_state(self, now=None):
        state = super().public_state(now)
        state.pop("held_items", None)
        state.pop("item_locations", None)
        state.update(objective="交换私有线索：监听员授权符号，现场员校准对应脉冲",
                     completed_items=list(STAGES[:self.stage_index]),
                     next_item=STAGES[self.stage_index] if self.stage_index < 3 else None,
                     stage=min(self.stage_index + 1, 3), stage_count=3,
                     authorized=self.authorized,
                     voice_examples=["先与同伴交换线索，再说授权或校准指令"],
                     chapter_tasks=list(STAGES),
                     ending="你们识破了监听者的模仿，共同逃离。下一章：失真的求救。" if self.phase == "won" else None)
        return state

    def private_briefing(self, player):
        role = self.roles[player]
        text = "等待两名玩家就绪。"
        if self.puzzles and self.stage_index < 3:
            puzzle = self.puzzles[self.stage_index]
            if role == "现场员":
                text = "；".join(f"{symbol}对应{signals[0]}，也可以描述为{signals[1]}"
                                for symbol, signals in puzzle["mapping"].items())
                text += "。请向同伴询问目标，再说‘校准’加对应特征。"
            else:
                text = f"本阶段安全符号是{puzzle['target']}。请说‘授权{puzzle['target']}’，让同伴辨认对应特征。"
        return {"type": "private_briefing", "role": role, "text": text, "stage": self.stage_index + 1}

    def process_utterance(self, player_id, text, source="stt"):
        text = text.strip()[:200]
        if not text:
            return []
        events = [self._event("transcript", player_id=player_id, text=text, source=source)]
        timeout = self.tick()
        if timeout:
            return events + [timeout]
        if self.phase != "active":
            return events
        if player_id not in self.roles:
            return events
        if any(word in text for word in self.forbidden_words):
            return events + [self._mistake(player_id, "forbidden_word", "监听者捕捉了危险表达；请换一种描述。")]
        puzzle = self.puzzles[self.stage_index]
        compact = normalize(text)
        role = self.roles[player_id]
        if "授权" in compact:
            if role != "监听员":
                return events + [self._event("clarification_needed", consequence="只有监听员能授权。")]
            if not any(symbol in compact for symbol in SYMBOL_ALIASES[puzzle["target"]]):
                return events + [self._mistake(player_id, "wrong_symbol", "授权符号与安全规则不符。")]
            self.authorized = True
            return events + [self._event("authorization_granted", consequence="授权生效，等待现场员校准。")]
        if "校准" not in compact:
            return events
        if role != "现场员" or not self.authorized:
            return events + [self._event("clarification_needed", consequence="需要监听员先授权，再由现场员校准。")]
        signals = puzzle["mapping"][puzzle["target"]]
        if not any(signal in compact for signal in signals):
            return events + [self._mistake(player_id, "wrong_signal", "信号不匹配，请交换线索后重试。")]
        self.stage_index += 1
        self.authorized = False
        if self.stage_index == 3:
            self.ended_remaining_time = self.remaining_time()
            self.phase = "won"
            self.last_consequence = "两路信号汇合，你们识破了监听者，共同逃离。"
            return events + [self._event("game_won", consequence=self.last_consequence)]
        if self.stage_index == 1:
            self.learned_phrase = next(signal for signal in signals if signal in compact)
            self.last_consequence = f"监听者学会了你们说过的‘{self.learned_phrase}’，以后说出它会暴露位置。换一种描述！"
            events.append(self._event("listener_learned", consequence=self.last_consequence))
        else:
            self.last_consequence = "最后一条频道恢复。交换新线索，共同点火。"
        return events + [self._event("stage_completed", consequence=self.last_consequence)]
