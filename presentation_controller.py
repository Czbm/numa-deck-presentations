"""Presentation use-case facade.

The main window remains the Qt composition root, while this facade keeps
external presentation commands in one small, testable boundary. It prevents
Mobile Link and future transports from reaching individual widgets directly.
"""

import time


class PresentationController:
    ACTIONS = {
        "next_slide": "presentation_next_slide",
        "previous_slide": "presentation_prev_slide",
        "open_image": "_open_presentation_image_from_presenter_action",
        "close_image": "_close_presentation_image_overlays",
        "zoom_in": "_adjust_presentation_image_zoom",
        "zoom_out": "_adjust_presentation_image_zoom",
        "toggle_pointer": "_toggle_mobile_pointer_visibility",
        "recenter_pointer": "_recenter_mobile_pointer",
        "increase_text": "increase_student_font_size",
        "decrease_text": "decrease_student_font_size",
        "toggle_theme": "toggle_theme",
    }

    def __init__(self, window):
        self.window = window
        self._action_count = 0
        self._last_action = None
        self._last_action_ms = None

    def dispatch_mobile_action(self, action):
        action = str(action or "").strip().lower()
        method_name = self.ACTIONS.get(action)
        if not method_name:
            return False
        handler = getattr(self.window, method_name, None)
        if not handler:
            return False
        started = time.perf_counter()
        if action == "zoom_in":
            handler("page_next")
        elif action == "zoom_out":
            handler("page_prev")
        else:
            handler()
        self._action_count += 1
        self._last_action = action
        self._last_action_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return True

    def diagnostics_snapshot(self):
        return {
            "action_count": self._action_count,
            "last_action": self._last_action,
            "last_action_ms": self._last_action_ms,
        }
