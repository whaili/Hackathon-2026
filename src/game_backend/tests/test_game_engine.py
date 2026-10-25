import unittest

from game_backend.game_engine import GameState, SirenLullabyState, SoloChallengeState, create_game


class GameStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = GameState()
        self.game.start()

    def test_forbidden_word_raises_alert_from_transcript(self) -> None:
        events = self.game.process_utterance("p1", "向左移动", source="stt")
        self.assertEqual(self.game.alert_level, 1)
        alert = next(event for event in events if event["type"] == "alert_raised")
        self.assertEqual(alert["reason"], "forbidden_word")
        self.assertNotEqual(self.game.forbidden_words, ("左", "右"))

    def test_expected_pick_and_place_rotates_forbidden_words(self) -> None:
        initial_words = self.game.forbidden_words
        self.game.process_utterance("p1", "拿起钥匙")
        events = self.game.process_utterance("p1", "把它放入逃生舱")
        self.assertEqual(self.game.completed_items, ["钥匙"])
        self.assertEqual(events[-1]["type"], "action_applied")
        self.assertNotEqual(self.game.forbidden_words, initial_words)

    def test_wrong_item_creates_a_chainable_error(self) -> None:
        events = self.game.process_utterance("p1", "拿起电池")
        self.assertEqual(self.game.error_count, 1)
        self.assertEqual(self.game.alert_level, 1)
        self.assertEqual(events[-1]["reason"], "wrong_item")

    def test_three_correct_items_win(self) -> None:
        for item in ("钥匙", "电池", "样本"):
            self.game.process_utterance("p1", f"拿起{item}")
            events = self.game.process_utterance("p1", "放入逃生舱")
        self.assertEqual(self.game.phase, "won")
        self.assertEqual(events[-1]["type"], "game_won")
        self.assertGreater(self.game.remaining_time(), 0)

    def test_timeout_loses(self) -> None:
        event = self.game.tick(now=(self.game.started_at or 0) + 91)
        self.assertEqual(self.game.phase, "lost")
        self.assertEqual(event["reason"], "timeout")


class SoloChallengeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = SoloChallengeState()
        self.game.start()

    def test_solo_requires_safe_voice_actions_to_escape(self) -> None:
        self.game.process_utterance("solo", "探索能源区")
        events = self.game.process_utterance("solo", "选择最尖锐的脉冲")
        self.assertEqual(events[-1]["type"], "stage_completed")
        self.assertEqual(self.game.stage_index, 1)

        self.game.process_utterance("solo", "检查控制台")
        self.game.process_utterance("solo", "校准稳定重复的频率")
        self.assertEqual(self.game.stage_index, 2)

        self.game.process_utterance("solo", "解除安全锁扣")
        events = self.game.process_utterance("solo", "启动主推进")
        self.assertEqual(events[-1]["type"], "game_won")
        self.assertEqual(self.game.phase, "won")

    def test_solo_forbidden_expression_raises_alert_and_blocks_action(self) -> None:
        events = self.game.process_utterance("solo", "选择左边那个")
        self.assertEqual(self.game.alert_level, 1)
        self.assertEqual(events[-1]["reason"], "forbidden_concept")
        self.assertEqual(self.game.stage_index, 0)

    def test_solo_requires_exploration_before_a_selection(self) -> None:
        events = self.game.process_utterance("solo", "选择最尖锐的脉冲")
        self.assertEqual(events[-1]["type"], "clarification_needed")
        self.assertEqual(self.game.stage_index, 0)

    def test_solo_help_costs_an_alert_and_is_limited(self) -> None:
        events = self.game.process_utterance("solo", "给我一个提示")
        self.assertEqual(events[-1]["type"], "help_used")
        self.assertEqual(self.game.help_remaining, 1)
        self.assertEqual(self.game.alert_level, 1)

    def test_create_game_selects_modes(self) -> None:
        self.assertEqual(create_game("solo").mode, "solo")
        self.assertEqual(create_game("duo").mode, "duo")


class SirenLullabyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = SirenLullabyState()
        self.game.start()

    def test_four_quiet_in_tune_bars_put_the_siren_to_sleep(self) -> None:
        for _ in range(3):
            self.assertEqual(self.game.process_metrics("p", pitch=0, volume=0.2, tempo=1.0)[-1]["type"], "bar_completed")
        self.assertEqual(self.game.process_metrics("p", pitch=0, volume=0.2, tempo=1.0)[-1]["type"], "game_won")

    def test_loud_or_off_tempo_singing_triggers_frenzy(self) -> None:
        event = self.game.process_metrics("p", pitch=0, volume=0.8, tempo=1.0)[-1]
        self.assertEqual(event["type"], "frenzy")
        self.assertTrue(event["distortion"])
        self.assertTrue(event["npc_attack"])

    def test_accessibility_mode_checks_lyrics_and_tempo_only(self) -> None:
        self.game.accessibility_mode = True
        for lyric in ("潮息归于静海", "月光覆过船底", "让歌声沉入梦乡", "四海无声安眠"):
            events = self.game.process_utterance("p", lyric)
        self.assertEqual(events[-1]["type"], "game_won")


if __name__ == "__main__":
    unittest.main()
