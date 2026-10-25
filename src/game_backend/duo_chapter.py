"""Server-authoritative two-role chapter with per-player clues."""

import secrets
import time
from dataclasses import dataclass, field

from .game_engine import GameState, normalize


SIGNALS = (("低沉脉冲", "厚重回声"), ("尖锐脉冲", "清亮回声"), ("断续脉冲", "停顿回声"))
SYMBOLS = ("星环", "月痕", "潮纹")
SYMBOL_ALIASES = {"星环": ("星环",), "月痕": ("月痕", "月恒", "月衡"),
                  "潮纹": ("潮纹", "潮文", "朝纹", "朝文")}
STAGES = ("接通能源", "辨认伪装", "共同抉择")


@dataclass
class DuoChapterState(GameState):
    mode_title = "分离频道 · 免费序章"
    duration_seconds: int = 720
    roles: dict = field(default_factory=dict)
    puzzles: list = field(default_factory=list)
    stage_index: int = 0
    authorized: bool = False
    learned_phrase: str = ""
    paused_at: float | None = None
    choices: dict = field(default_factory=dict)

    def remaining_time(self, now=None):
        return super().remaining_time(self.paused_at if self.paused_at is not None else now)

    def pause(self):
        if self.phase != "active" or self.paused_at is not None:
            return []
        self.paused_at = time.time()
        self.authorized = False
        return [self._event("partner_disconnected", consequence="同伴频道断开，倒计时已暂停。用原代号重连后继续。")]

    def resume(self):
        if self.paused_at is None:
            return []
        self.started_at += time.time() - self.paused_at
        self.paused_at = None
        return [self._event("partner_reconnected", consequence="同伴回到频道，倒计时继续。请重新确认当前阶段。")]

    def tick(self, now=None):
        return None if self.paused_at is not None else super().tick(now)

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
        self.paused_at = None
        self.choices.clear()
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
        objectives = ("交换私有线索：监听员授权符号，现场员校准对应脉冲", "识破监听者的假命令，用替代表达完成校准", "交换最后的信息，双方共同选择撤离或保留档案")
        state.update(objective=objectives[min(self.stage_index, 2)],
                     completed_items=list(STAGES[:self.stage_index]),
                     next_item=STAGES[self.stage_index] if self.stage_index < 3 else None,
                     stage=min(self.stage_index + 1, 3), stage_count=3,
                     authorized=self.authorized,
                     paused=self.paused_at is not None, final_choices=dict(self.choices),
                     voice_examples=["先与同伴交换线索，再说授权或校准指令"],
                     chapter_tasks=list(STAGES),
                     ending=("你们带走了档案，也带走了监听者的追踪。下一章：失真的求救。" if "保留档案" in self.choices.values()
                             else "你们放弃档案，选择彼此，共同逃离。下一章：失真的求救。") if self.phase == "won" else None)
        return state

    def private_briefing(self, player):
        role = self.roles[player]
        text = "等待两名玩家就绪。"
        if self.phase in {"won", "lost"}:
            text = "本章已结束。你们可以再次挑战，交换角色体验不同的线索。"
        elif self.stage_index == 2:
            text = ("你的任务：现场员负责执行校准。两人都可以撤离，但携带档案会留下可追踪信号。"
                    if role == "现场员" else "你的任务：监听员负责确认规则。两人须作出一致选择，舱门才会解锁。")
            text += "\n先交换意见，再各自说‘确认撤离’或‘保留档案’。选择不同可重新协商。"
        elif self.puzzles and self.stage_index < 2:
            puzzle = self.puzzles[self.stage_index]
            if role == "现场员":
                text = "；".join(f"{symbol}对应{signals[0]}，也可以描述为{signals[1]}"
                                for symbol, signals in puzzle["mapping"].items())
                text = "你的任务：把同伴报出的符号翻译成声音特征。\n" + text
                text += "。\n行动顺序：先问监听员目标符号，再说‘校准’加对应特征。"
            else:
                verb = "识别伪装，安全符号是" if self.stage_index == 1 else "授权"
                text = f"你的任务：报出你手里的安全符号，让现场员执行。\n本阶段安全符号是{puzzle['target']}。请说‘{verb}{puzzle['target']}’。"
                if self.stage_index == 1:
                    text += "\n频道里那个熟悉的命令来自监听者；不要照着重复。"
        return {"type": "private_briefing", "role": role, "text": text, "stage": min(self.stage_index + 1, 3)}

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
        if self.paused_at is not None:
            return events + [self._event("clarification_needed", consequence="等待同伴重连，当前不会推进游戏。")]
        if player_id not in self.roles:
            return events
        if any(word in text for word in self.forbidden_words):
            return events + [self._mistake(player_id, "forbidden_word", "监听者捕捉了危险表达；请换一种描述。")]
        puzzle = self.puzzles[self.stage_index]
        compact = normalize(text)
        role = self.roles[player_id]
        expose = any(verb in compact for verb in ("识破", "石破", "识别伪装", "辨认伪装"))
        if self.stage_index == 2:
            choice = next((choice for choice in ("确认撤离", "保留档案") if choice in compact), None)
            if not choice:
                return events
            self.choices[player_id] = choice
            if len(self.choices) == 2 and len(set(self.choices.values())) == 1:
                self.ended_remaining_time = self.remaining_time()
                self.phase = "won"
                self.stage_index = 3
                self.last_consequence = self.public_state()["ending"]
                return events + [self._event("game_won", consequence=self.last_consequence, narration=self.last_consequence)]
            event = "choice_mismatch" if len(self.choices) == 2 else "choice_recorded"
            return events + [self._event(event, consequence="你们的选择还不一致，请协商后重新确认。" if len(self.choices) == 2 else "你的选择已记录，等待同伴表态。")]
        if "授权" in compact or expose:
            if role != "监听员":
                return events + [self._event("clarification_needed", consequence="只有监听员能授权。")]
            if self.stage_index == 1 and not expose:
                return events + [self._event("clarification_needed", consequence="这次先由监听员识破假信号，再让现场员换一种描述。")]
            if not any(symbol in compact for symbol in SYMBOL_ALIASES[puzzle["target"]]):
                return events + [self._mistake(player_id, "wrong_symbol", "授权符号与安全规则不符。")]
            self.authorized = True
            return events + [self._event("authorization_granted", consequence="识破伪装，等待安全校准。" if self.stage_index == 1 else "授权生效，等待现场员校准。")]
        if "校准" not in compact:
            return events
        if role != "现场员" or not self.authorized:
            return events + [self._event("clarification_needed", consequence="需要监听员先授权，再由现场员校准。")]
        signals = puzzle["mapping"][puzzle["target"]]
        if not any(signal in compact for signal in signals):
            return events + [self._mistake(player_id, "wrong_signal", "信号不匹配，请交换线索后重试。")]
        self.stage_index += 1
        self.authorized = False
        if self.stage_index == 1:
            self.learned_phrase = next(signal for signal in signals if signal in compact)
            # The next puzzle deliberately points at the learned signal so
            # changing one's phrasing is necessary, not an optional flourish.
            next_puzzle = self.puzzles[1]
            matching_symbol = next(symbol for symbol, pair in next_puzzle["mapping"].items() if signals == pair)
            next_puzzle["target"] = matching_symbol
            self.last_consequence = f"监听者学会了你们说过的‘{self.learned_phrase}’，以后说出它会暴露位置。换一种描述！"
            events.append(self._event("listener_learned", consequence=self.last_consequence))
            events.append(self._event("listener_imitation", consequence=f"频道传来熟悉的声音：继续校准{self.learned_phrase}。这真的是你的同伴吗？",
                                      narration=f"继续校准{self.learned_phrase}。"))
        else:
            self.last_consequence = "出口恢复，但档案留下了追踪信号。交换最后的信息，共同选择撤离还是保留档案。"
        return events + [self._event("stage_completed", consequence=self.last_consequence)]
