"""Regression tests for critical non-visual Desk flows.

These tests intentionally avoid constructing the full QMainWindow. GUI and
WebEngine behavior remains a separate manual/dynamic verification phase.
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")

import main
from mobile_link import MobileLinkServer


class _RecoveryHarness:
    """Minimal receiver for unbound recovery methods from NumaDeckWindow."""

    AUTOSAVE_RETENTION_DAYS = main.NumaDeckWindow.AUTOSAVE_RETENTION_DAYS

    def __init__(self):
        self.operations = []

    def _log_operation(self, name, **details):
        self.operations.append((name, details))

    def _write_recovery_copy(self, path, content):
        return main.NumaDeckWindow._write_recovery_copy(self, path, content)

    @classmethod
    def _autosave_paths_for_document(cls, path):
        return main.NumaDeckWindow._autosave_paths_for_document(path)

    @staticmethod
    def _autosave_root():
        return main.NumaDeckWindow._autosave_root()


def test_dual_document_sources_are_scoped_to_one_tab():
    tab = {
        "path": r"C:\docs\student.md",
        "content": "student",
        "teacher_script_path": r"C:\docs\teacher.md",
        "teacher_script_content": "teacher",
    }
    sources = main.NumaDeckWindow._document_sources_for_tab(None, tab)
    assert sources == [
        (r"C:\docs\student.md", "student"),
        (r"C:\docs\teacher.md", "teacher"),
    ]


def test_autosave_sources_exclude_clean_tabs():
    clean_tab = {
        "path": r"C:\docs\student.md",
        "content": "stale in-memory content",
        "teacher_script_path": r"C:\docs\teacher.md",
        "teacher_script_content": "stale teacher content",
        "modified": False,
        "teacher_modified": False,
    }
    dirty_tab = dict(clean_tab, modified=True)
    assert main.NumaDeckWindow._document_sources_for_tab(
        None, clean_tab, modified_only=True
    ) == []
    assert main.NumaDeckWindow._document_sources_for_tab(
        None, dirty_tab, modified_only=True
    ) == [(r"C:\docs\student.md", "stale in-memory content")]


def test_tab_switch_backs_up_latest_editor_without_overwriting_original():
    with tempfile.TemporaryDirectory() as root:
        original = Path(root) / "student.md"
        original.write_text("saved", encoding="utf-8")

        class Harness(_RecoveryHarness):
            _document_sources_for_tab = main.NumaDeckWindow._document_sources_for_tab
            _write_autosave = main.NumaDeckWindow._write_autosave

            def _sync_current_tab_from_editor(self):
                self.tabs[0]["content"] = "latest unsaved edit"

            def _load_tab(self, index):
                backup, _ = self.recovery_service.paths_for_document(str(original))
                assert backup.read_text(encoding="utf-8") == "latest unsaved edit"
                self.current_tab_index = index

        harness = Harness()
        harness.recovery_service = main.RecoveryService(root=Path(root) / "backups")
        harness._loading_tab = False
        harness.current_tab_index = 0
        harness.tabs = [{"path": str(original), "content": "older edit",
                         "presentation_script_content": "", "modified": True}, {}]
        main.NumaDeckWindow._switch_to_tab(harness, 1)
        assert original.read_text(encoding="utf-8") == "saved"
        assert harness.tabs[0]["content"] == "latest unsaved edit"


def test_loaded_tab_does_not_repeat_recovery_check():
    class StopLoading(Exception):
        pass

    class Harness:
        def __init__(self):
            self.tabs = [{}]
            self.checks = 0

        def _check_tab_autosaves(self, tab):
            self.checks += 1

        def __setattr__(self, name, value):
            if name == "_loading_tab" and value:
                raise StopLoading()
            object.__setattr__(self, name, value)

    harness = Harness()
    for _ in range(2):
        try:
            main.NumaDeckWindow._load_tab(harness, 0)
        except StopLoading:
            pass
    assert harness.checks == 1


def test_shortcut_definitions_are_unique_and_complete():
    definitions = main.NumaDeckWindow.SHORTCUT_DEFINITIONS
    action_ids = [item[0] for item in definitions]
    assert len(action_ids) == len(set(action_ids))
    assert {item[0] for item in definitions} >= {
        "slide_anterior",
        "slide_siguiente",
        "presentacion_salir",
        "imagen_abrir",
        "imagen_pantalla_completa",
        "imagen_zoom_mas",
        "imagen_zoom_menos",
        "zoom_mas",
        "zoom_menos",
        "barra_markdown",
    }
    assert all(item[2] for item in definitions)


def test_autosave_is_atomic_and_recoverable():
    with tempfile.TemporaryDirectory() as temp_root:
        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = temp_root
        try:
            original = Path(temp_root) / "student.md"
            original.write_text("original\n", encoding="utf-8")
            harness = _RecoveryHarness()
            assert main.NumaDeckWindow._write_autosave(
                harness, str(original), "edited\n"
            )
            backup_path, meta_path = main.NumaDeckWindow._autosave_paths_for_document(str(original))
            assert backup_path.read_text(encoding="utf-8") == "edited\n"
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            assert metadata["clean_snapshot"] is False
            assert not list(backup_path.parent.glob("*.tmp"))
        finally:
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous


def test_clean_autosave_is_not_created_and_stale_pair_is_removed():
    with tempfile.TemporaryDirectory() as temp_root:
        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = temp_root
        try:
            original = Path(temp_root) / "student.md"
            original.write_text("original\n", encoding="utf-8")
            harness = _RecoveryHarness()
            assert not main.NumaDeckWindow._write_autosave(
                harness, str(original), "original\n"
            )
            backup_path, meta_path = main.NumaDeckWindow._autosave_paths_for_document(str(original))
            assert not backup_path.exists() and not meta_path.exists()

            assert main.NumaDeckWindow._write_autosave(
                harness, str(original), "edited\n"
            )
            assert backup_path.exists() and meta_path.exists()
            assert not main.NumaDeckWindow._write_autosave(
                harness, str(original), "original\n"
            )
            assert not backup_path.exists() and not meta_path.exists()
        finally:
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous


def test_clean_close_removes_recovery_pair():
    with tempfile.TemporaryDirectory() as temp_root:
        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = temp_root
        try:
            original = Path(temp_root) / "student.md"
            original.write_text("original\n", encoding="utf-8")
            service = main.RecoveryService(root=Path(temp_root) / "autosaves")
            service.write_recovery_copy(str(original), "edited\n", clean_snapshot=False)
            backup_path, meta_path = service.paths_for_document(str(original))
            assert backup_path.exists() and meta_path.exists()
            assert service.refresh_clean_backups([(str(original), "original\n")]) == 2
            assert not backup_path.exists() and not meta_path.exists()
        finally:
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous


def test_normal_save_invalidates_stale_recovery_pair():
    """A recovery copy from before a normal save must not prompt later."""
    with tempfile.TemporaryDirectory() as temp_root:
        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = temp_root
        try:
            original = Path(temp_root) / "student.md"
            original.write_text("original\n", encoding="utf-8")
            harness = _RecoveryHarness()
            assert main.NumaDeckWindow._write_autosave(
                harness, str(original), "edited\n"
            )
            backup_path, meta_path = main.NumaDeckWindow._autosave_paths_for_document(str(original))
            assert backup_path.exists() and meta_path.exists()

            # The user saves the same content that was in the recovery copy.
            original.write_text("edited\n", encoding="utf-8")
            main.NumaDeckWindow._remove_autosave(harness, str(original))

            service = main.RecoveryService(root=Path(temp_root) / "autosaves")
            assert service.inspect(str(original)) is None
        finally:
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous


def test_purge_removes_old_clean_copy_but_keeps_changed_copy():
    with tempfile.TemporaryDirectory() as temp_root:
        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = temp_root
        try:
            root = Path(temp_root) / "autosaves"
            service = main.RecoveryService(root=root)
            clean_original = Path(temp_root) / "clean.md"
            changed_original = Path(temp_root) / "changed.md"
            clean_original.write_text("same", encoding="utf-8")
            changed_original.write_text("original", encoding="utf-8")
            service.write_recovery_copy(str(clean_original), "same", clean_snapshot=True)
            service.write_recovery_copy(str(changed_original), "edited", clean_snapshot=False)
            for meta_path in root.glob("*.json"):
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                metadata["created_at"] = (
                    time.time() - 4 * 86400
                    if metadata["original_path"] == str(clean_original)
                    else time.time()
                )
                meta_path.write_text(json.dumps(metadata), encoding="utf-8")
            assert service.purge_expired() == 2
            clean_backup, clean_meta = service.paths_for_document(str(clean_original))
            changed_backup, changed_meta = service.paths_for_document(str(changed_original))
            assert not clean_backup.exists() and not clean_meta.exists()
            assert changed_backup.exists() and changed_meta.exists()
        finally:
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous


def test_autosave_retention_removes_only_expired_entries():
    with tempfile.TemporaryDirectory() as temp_root:
        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = temp_root
        try:
            root = main.NumaDeckWindow._autosave_root()
            old_meta = root / "old.json"
            old_backup = root / "old.md"
            fresh_meta = root / "fresh.json"
            fresh_backup = root / "fresh.md"
            old_meta.write_text(json.dumps({"created_at": time.time() - 4 * 86400}), encoding="utf-8")
            old_backup.write_text("old", encoding="utf-8")
            fresh_meta.write_text(json.dumps({"created_at": time.time()}), encoding="utf-8")
            fresh_backup.write_text("fresh", encoding="utf-8")
            harness = _RecoveryHarness()
            main.NumaDeckWindow._purge_expired_autosaves(harness)
            assert not old_meta.exists() and not old_backup.exists()
            assert fresh_meta.exists() and fresh_backup.exists()
        finally:
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous


class _FakeWebSocket:
    remote_address = ("127.0.0.1", 12345)

    def __init__(self, messages, path="/?token=test-token"):
        self.messages = iter(messages)
        self.sent = []
        self.path = path
        self.closed = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def close(self, code=None, reason=None):
        self.closed = (code, reason)


def test_mobile_link_emits_hello_and_rejects_invalid_json_without_crashing():
    server = MobileLinkServer(host="127.0.0.1", port=0, auth_token="test-token")
    received = []
    server.message_received.connect(received.append)
    websocket = _FakeWebSocket([
        "{invalid",
        json.dumps({"version": 1, "type": "hello", "sequence": 1, "timestamp": 1, "payload": {"client_name": "test", "protocol_version": 1}}),
    ])
    asyncio.run(server._handle_client(websocket))
    assert websocket.sent[0]["type"] == "error"
    assert websocket.sent[0]["payload"]["message"] == "JSON inválido"
    assert received[0]["type"] == "hello"
    assert received[0]["_remote"] == "('127.0.0.1', 12345)"


def test_mobile_link_client_count_returns_to_zero_after_disconnect():
    server = MobileLinkServer(host="127.0.0.1", port=0, auth_token="test-token")
    websocket = _FakeWebSocket([])
    asyncio.run(server._handle_client(websocket))
    assert server.client_count == 0


def test_mobile_link_rejects_invalid_pairing_token_before_emitting_messages():
    server = MobileLinkServer(host="127.0.0.1", port=0, auth_token="test-token")
    received = []
    server.message_received.connect(received.append)
    websocket = _FakeWebSocket([
        json.dumps({"version": 1, "type": "hello", "sequence": 1, "timestamp": 1, "payload": {"client_name": "test", "protocol_version": 1}}),
    ], path="/?token=wrong-token")
    import asyncio
    asyncio.run(server._handle_client(websocket))
    assert not received
    assert websocket.sent[-1]["type"] == "error"
    assert websocket.closed == (1008, "invalid pairing token")


class _PointerTarget:
    def __init__(self):
        self.config = None
        self.position = None

    def set_mobile_pointer_config(self, **config):
        self.config = config

    def set_mobile_pointer(self, x, y, visible):
        self.position = (x, y, visible)


class _PointerHarness:
    def __init__(self):
        self._mobile_pointer_config = {"size": 24, "shape": "ring", "color": "#39FF14", "trail": 0}
        self._mobile_pointer_config_version = 3
        self._mobile_pointer_applied_versions = {}
        self._mobile_pointer_visible = True
        self._mobile_pointer_pending = None
        self.is_fullscreen_presentation = False
        self.target = _PointerTarget()
        self.operations = []

    def _presentation_student_view(self):
        return self.target

    def _log_operation(self, name, **details):
        self.operations.append((name, details))

    def statusBar(self):
        class _StatusBar:
            @staticmethod
            def showMessage(*args):
                return None
        return _StatusBar()


class _IndependentMouseHarness(_PointerHarness):
    def __init__(self):
        super().__init__()
        self.is_fullscreen_presentation = True
        self.mouse_events = []

    def _presentation_student_view(self):
        class _MouseTarget:
            def __init__(self, events):
                self.events = events

            def mobile_mouse_move(self, x, y):
                self.events.append(("move", x, y))

            def mobile_mouse_click(self, x, y, click_count):
                self.events.append(("click", x, y, click_count))

            def mobile_mouse_scroll(self, x, y, delta_y):
                self.events.append(("scroll", x, y, delta_y))

        return _MouseTarget(self.mouse_events)

    def _on_mobile_link_message(self, message):
        return main.NumaDeckWindow._on_mobile_link_message(self, message)


def test_mousepad_events_are_independent_from_pointer_visibility():
    harness = _IndependentMouseHarness()
    harness._on_mobile_link_message({
        "type": "mouse_move",
        "payload": {"x": 0.2, "y": 0.3},
        "_remote": "test",
    })
    harness._on_mobile_link_message({
        "type": "mouse_click",
        "payload": {"x": 0.2, "y": 0.3, "click_count": 1},
        "_remote": "test",
    })
    harness._on_mobile_link_message({
        "type": "mouse_scroll",
        "payload": {"x": 0.2, "y": 0.3, "delta_y": 0.5},
        "_remote": "test",
    })
    assert [event[0] for event in harness.mouse_events] == ["move", "click", "scroll"]


def test_recenter_pointer_updates_the_active_slide_pointer():
    harness = _PointerHarness()
    main.NumaDeckWindow._recenter_mobile_pointer(harness)
    assert harness._mobile_pointer_pending == (0.5, 0.5)
    assert harness.target.position == (0.5, 0.5, True)
    assert harness.operations[-1][0] == "mobile_link_pointer_recentrado"


class _AutosaveScopeHarness:
    def __init__(self):
        self.checked = []

    def _read_with_autosave_offer(self, path, role_label, fallback_text=None):
        self.checked.append((path, role_label))
        return fallback_text or "", False


def test_autosave_check_can_be_limited_to_the_source_being_loaded():
    tab = {
        "path": r"C:\docs\student.md",
        "content": "student",
        "teacher_script_path": r"C:\docs\teacher.md",
        "teacher_script_content": "teacher",
        "teacher_preview_mode": "dual",
    }
    harness = _AutosaveScopeHarness()
    main.NumaDeckWindow._check_tab_autosaves(
        harness,
        tab,
        check_student=False,
        check_teacher=True,
    )
    assert harness.checked == [(r"C:\docs\teacher.md", "el guion del profesor")]


if __name__ == "__main__":
    for test in (
        test_dual_document_sources_are_scoped_to_one_tab,
        test_autosave_sources_exclude_clean_tabs,
        test_tab_switch_backs_up_latest_editor_without_overwriting_original,
        test_loaded_tab_does_not_repeat_recovery_check,
        test_shortcut_definitions_are_unique_and_complete,
        test_autosave_is_atomic_and_recoverable,
        test_normal_save_invalidates_stale_recovery_pair,
        test_autosave_retention_removes_only_expired_entries,
        test_mobile_link_emits_hello_and_rejects_invalid_json_without_crashing,
        test_mobile_link_client_count_returns_to_zero_after_disconnect,
        test_mousepad_events_are_independent_from_pointer_visibility,
    ):
        test()
    print("REGRESSION TESTS PASSED")
