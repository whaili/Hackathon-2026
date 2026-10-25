import json
import unittest

from game_backend.duo_chapter import DuoChapterState, STAGES


class DuoChapterTests(unittest.TestCase):
    def setUp(self):
        self.game = DuoChapterState()
        self.game.register("alice")
        self.game.register("bob")
        self.game.start()

    def choice(self):
        puzzle = self.game.puzzles[self.game.stage_index]
        return puzzle["target"], puzzle["mapping"][puzzle["target"]]

    def test_both_roles_are_required(self):
        target, signals = self.choice()
        event = self.game.process_utterance("alice", f"授权{target}")[-1]
        self.assertEqual(event["type"], "clarification_needed")
        self.game.process_utterance("bob", f"授权{target}")
        self.game.process_utterance("bob", f"校准{signals[0]}")
        self.assertEqual(self.game.stage_index, 0)
        self.game.process_utterance("alice", f"校准{signals[0]}")
        self.assertEqual(self.game.stage_index, 1)

    def test_clues_are_private_and_slot_limit_survives_reconnect(self):
        public = json.dumps(self.game.public_state(), ensure_ascii=False)
        self.assertNotIn("mapping", public)
        self.assertNotIn("target", public)
        self.assertNotIn("安全符号", public)
        for signals in self.game.puzzles[0]["mapping"].values():
            for signal in signals:
                self.assertNotIn(signal, self.game.private_briefing("bob")["text"])
        self.assertNotIn("安全符号是", self.game.private_briefing("alice")["text"])
        self.assertTrue(self.game.register("alice"))
        self.assertFalse(self.game.register("eve"))

    def test_listener_learns_spoken_phrase_and_safe_alternative_can_win(self):
        target, signals = self.choice()
        self.game.process_utterance("bob", f"授权{target}")
        events = self.game.process_utterance("alice", f"校准{signals[0]}")
        self.assertIn("listener_learned", [event["type"] for event in events])
        self.assertEqual(self.game.learned_phrase, signals[0])
        self.assertEqual(self.game.process_utterance("alice", signals[0])[-1]["type"], "alert_raised")
        for _ in range(2):
            target, signals = self.choice()
            self.game.process_utterance("bob", f"授权{target}")
            safe = next(signal for signal in signals if signal != self.game.learned_phrase)
            self.game.process_utterance("alice", f"校准{safe}")
        self.assertEqual(self.game.phase, "won")
        self.assertEqual(self.game.public_state()["completed_items"], list(STAGES))

    def test_wrong_signal_does_not_advance_and_alert_limit_loses(self):
        target, _ = self.choice()
        self.game.process_utterance("bob", f"授权{target}")
        for _ in range(5):
            self.game.process_utterance("alice", "校准未知信号")
        self.assertEqual(self.game.stage_index, 0)
        self.assertEqual(self.game.phase, "lost")

    def test_known_asr_homophone_is_accepted_but_other_symbol_is_not(self):
        self.game.puzzles[0]["target"] = "潮纹"
        event = self.game.process_utterance("bob", "授权星环")[-1]
        self.assertEqual(event["reason"], "wrong_symbol")
        event = self.game.process_utterance("bob", "授权潮文")[-1]
        self.assertEqual(event["type"], "authorization_granted")
