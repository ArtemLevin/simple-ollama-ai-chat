from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

import tkinter as tk

base = types.ModuleType("ollama_gui_chat")
base.tk = tk

logged = types.ModuleType("ollama_gui_logged")
logged.base = base
logged.LOGGER = __import__("logging").getLogger("test")
logged.LoggedOllamaChatApp = type("LoggedOllamaChatApp", (), {})
logged.describe_text = lambda text: f"chars={len(text)}"
original_logged = sys.modules.get("ollama_gui_logged")
sys.modules["ollama_gui_logged"] = logged

spec = importlib.util.spec_from_file_location(
    "ollama_gui_clipboard",
    Path(__file__).parents[1] / "ollama_gui_clipboard.py",
)
assert spec and spec.loader
clipboard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = clipboard
spec.loader.exec_module(clipboard)
if original_logged is None:
    sys.modules.pop("ollama_gui_logged", None)
else:
    sys.modules["ollama_gui_logged"] = original_logged


class FakeWidget:
    def __init__(self, *, selection: str | None = None, state: str = "normal") -> None:
        self.selection = selection
        self.state = state

    def tag_ranges(self, tag: str):
        assert tag == "sel"
        return ("1.0", "1.1") if self.selection is not None else ()

    def get(self, start: str, end: str) -> str:
        assert (start, end) == ("sel.first", "sel.last")
        if self.selection is None:
            raise tk.TclError("no selection")
        return self.selection

    def cget(self, option: str) -> str:
        assert option == "state"
        return self.state


class ClipboardHelperTests(unittest.TestCase):
    def test_selected_text_returns_current_selection(self) -> None:
        self.assertEqual(clipboard.selected_text(FakeWidget(selection="ответ")), "ответ")

    def test_selected_text_returns_none_without_selection(self) -> None:
        self.assertIsNone(clipboard.selected_text(FakeWidget()))

    def test_read_only_widget_blocks_destructive_shortcuts(self) -> None:
        self.assertEqual(
            clipboard.action_for_windows_keycode(67, editable=False),
            "copy",
        )
        self.assertIsNone(clipboard.action_for_windows_keycode(86, editable=False))
        self.assertIsNone(clipboard.action_for_windows_keycode(88, editable=False))

    def test_editable_widget_allows_copy_paste_cut_and_select_all(self) -> None:
        expected = {65: "select_all", 67: "copy", 86: "paste", 88: "cut"}
        actual = {
            keycode: clipboard.action_for_windows_keycode(keycode, editable=True)
            for keycode in expected
        }
        self.assertEqual(actual, expected)
        self.assertTrue(clipboard.widget_is_editable(FakeWidget(state="normal")))
        self.assertFalse(clipboard.widget_is_editable(FakeWidget(state="disabled")))


if __name__ == "__main__":
    unittest.main()
