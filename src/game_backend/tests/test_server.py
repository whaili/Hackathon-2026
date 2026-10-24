import unittest

from fastapi.testclient import TestClient

from game_backend.server import (
    app,
    continuous_lingxi_sessions,
    lingxi_sessions,
    rooms,
)


class ServerStateMachineTests(unittest.TestCase):
    def test_websocket_text_drives_the_same_state_machine(self) -> None:
        with TestClient(app) as client:
            room_id = client.post("/api/rooms").json()["room_id"]
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

    def test_continuous_mcp_action_does_not_execute_twice(self) -> None:
        with TestClient(app) as client:
            room_id = client.post("/api/rooms").json()["room_id"]
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
