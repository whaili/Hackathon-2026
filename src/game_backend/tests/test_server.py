import unittest

from fastapi.testclient import TestClient

from game_backend.server import (
    app,
    continuous_lingxi_sessions,
    lingxi_sessions,
    rooms,
)


class ServerStateMachineTests(unittest.TestCase):
    def test_room_mode_selects_the_solo_engine(self) -> None:
        with TestClient(app) as client:
            response = client.post("/api/rooms", json={"mode": "solo"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"]["mode"], "solo")
        self.assertEqual(response.json()["state"]["mode_title"], "单人挑战 · 静默协议")

    def test_siren_room_accepts_audio_metrics(self) -> None:
        with TestClient(app) as client:
            room_id = client.post("/api/rooms", json={"mode": "siren"}).json()["room_id"]
            with client.websocket_connect(f"/ws/{room_id}?player_id=voice") as socket:
                socket.receive_json()
                socket.receive_json()
                socket.send_json({"type": "game_start"})
                socket.receive_json()
                socket.send_json({"type": "siren_metrics", "pitch": 0, "volume": 0.2, "tempo": 1.0})
                self.assertEqual(socket.receive_json()["event"]["type"], "bar_completed")
        task = rooms[room_id].timer_task
        if task:
            task.cancel()

    def test_websocket_text_drives_the_same_state_machine(self) -> None:
        with TestClient(app) as client:
            room_id = client.post("/api/rooms", json={"mode": "duo"}).json()["room_id"]
            with client.websocket_connect(f"/ws/{room_id}?player_id=tester") as socket:
                socket.receive_json()
                socket.receive_json()
                socket.send_json({"type": "game_start"})
                self.assertEqual(socket.receive_json()["event"]["type"], "game_started")
                socket.send_json({"type": "say", "text": "拿起钥匙"})
                self.assertEqual(socket.receive_json()["event"]["type"], "transcript")
                action = socket.receive_json()
                self.assertEqual(action["event"]["type"], "action_applied")
                self.assertEqual(action["state"]["held_items"], {"tester": "钥匙"})
        task = rooms[room_id].timer_task
        if task:
            task.cancel()

    def test_websocket_can_complete_the_solo_challenge(self) -> None:
        with TestClient(app) as client:
            room_id = client.post("/api/rooms", json={"mode": "solo"}).json()["room_id"]
            with client.websocket_connect(f"/ws/{room_id}?player_id=solo") as socket:
                socket.receive_json()
                socket.receive_json()
                socket.send_json({"type": "game_start"})
                self.assertEqual(socket.receive_json()["event"]["type"], "game_started")
                for phrase in (
                    "探索能源区", "选择最尖锐的脉冲", "检查控制台",
                    "校准稳定重复的频率", "解除安全锁扣", "启动主推进",
                ):
                    socket.send_json({"type": "say", "text": phrase})
                    socket.receive_json()  # transcript
                    event = socket.receive_json()
                self.assertEqual(event["event"]["type"], "game_won")
                self.assertEqual(event["state"]["mode"], "solo")
        task = rooms[room_id].timer_task
        if task:
            task.cancel()

    def test_continuous_mcp_action_does_not_execute_twice(self) -> None:
        with TestClient(app) as client:
            room_id = client.post("/api/rooms", json={"mode": "duo"}).json()["room_id"]
            room = rooms[room_id]
            room.game.start()
            session_id = "continuous-test-session"
            lingxi_sessions[session_id] = (room_id, "tester")
            continuous_lingxi_sessions.add(session_id)
            response = client.post(
                "/mcp",
                headers={"X-Linx-Session-Id": session_id},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "game.apply_action", "arguments": {"action": "拿起钥匙"}},
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(room.game.held_items, {})
        continuous_lingxi_sessions.discard(session_id)
        lingxi_sessions.pop(session_id, None)


if __name__ == "__main__":
    unittest.main()
