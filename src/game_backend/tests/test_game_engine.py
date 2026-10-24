import unittest

from game_backend.game_engine import GameState


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


if __name__ == "__main__":
    unittest.main()
