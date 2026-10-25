import unittest
from unittest.mock import patch

from game_backend.linx_client import PooledLingxiSession, configured_device_ids, _leased_devices


class DevicePoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_devices_are_exclusive_and_released_exactly_once(self):
        with patch.dict("os.environ", {"LINX_DEVICE_IDS": "device-a,device-b"}):
            alice = PooledLingxiSession()
            bob = PooledLingxiSession()
            self.assertNotEqual(alice.device_id, bob.device_id)
            with self.assertRaises(RuntimeError):
                PooledLingxiSession()
            await alice.close()
            replacement = PooledLingxiSession()
            await alice.close()
            self.assertIn(replacement.device_id, _leased_devices)
            await replacement.close()
            await bob.close()

    async def test_single_device_configuration_cannot_replace_an_active_player(self):
        with patch.dict("os.environ", {"LINX_DEVICE_IDS": "", "LINX_DEVICE_ID": "single-device"}):
            player = PooledLingxiSession()
            try:
                with self.assertRaises(RuntimeError):
                    PooledLingxiSession()
            finally:
                await player.close()

    async def test_duplicate_device_ids_are_rejected(self):
        with patch.dict("os.environ", {"LINX_DEVICE_IDS": "device-a,DEVICE-A"}):
            with self.assertRaises(RuntimeError):
                configured_device_ids()
