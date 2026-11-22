"""QR activation flow with a fake receiver; no radio settings are changed."""
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from direct_connections_dialog import DirectConnectionsDialog


class FakeConnections:
    receiver = SimpleNamespace(auth_token='test-token', port=8765)

    def __init__(self):
        self.states = {'bluetooth': ('off', {}), 'wifi_direct': ('off', {})}
        self.starts = []

    def snapshot(self, mode):
        return self.states[mode]

    def start(self, mode):
        self.starts.append(mode)
        self.states[mode] = ('starting', {})


class PairingQRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.connections = FakeConnections()
        self.dialog = DirectConnectionsDialog(self.connections)
        self.shown = []
        self.dialog._show_qr = self.shown.append

    def tearDown(self):
        self.dialog.reject()

    def test_qr_activates_and_waits_until_ready(self):
        qr = self.dialog.controls['bluetooth'][5]
        self.assertTrue(qr.isEnabled())
        qr.click()
        self.assertEqual(self.connections.starts, ['bluetooth'])
        self.assertEqual(self.shown, [])
        self.assertFalse(qr.isEnabled())
        self.connections.states['bluetooth'] = ('ready', {'service_name': 'NUMA Deck Mobile'})
        self.dialog.refresh()
        self.dialog.refresh()
        self.assertEqual(self.shown, ['bluetooth'])
        self.assertEqual(self.dialog.controls['bluetooth'][1]['service_name'].text(), 'NUMA Deck Mobile')

    def test_error_allows_retry_without_showing_qr(self):
        self.dialog._request_qr('bluetooth')
        self.connections.states['bluetooth'] = ('error', {'error': 'Radio unavailable'})
        self.dialog.refresh()
        self.assertEqual(self.shown, [])
        self.assertTrue(self.dialog.controls['bluetooth'][5].isEnabled())
        self.dialog._request_qr('bluetooth')
        self.assertEqual(len(self.connections.starts), 2)

    def test_ready_qr_does_not_restart_and_close_cancels_pending(self):
        self.connections.states['bluetooth'] = ('ready', {})
        self.dialog._request_qr('bluetooth')
        self.assertEqual(self.connections.starts, [])
        self.assertEqual(self.shown, ['bluetooth'])
        self.dialog._request_qr('wifi_direct')
        self.dialog.reject()
        self.assertFalse(self.dialog._pending_qr)


if __name__ == '__main__':
    unittest.main()
