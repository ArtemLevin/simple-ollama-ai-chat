from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any, Literal

import ollama_gui_logged as logged

base = logged.base
LOGGER = logged.LOGGER

ClipboardAction = Literal["copy", "cut", "paste", "select_all"]
WINDOWS_CTRL_KEYCODES: dict[int, ClipboardAction] = {
    65: "select_all",
    67: "copy",
    86: "paste",
    88: "cut",
}


def selected_text(widget: Any) -> str | None:
    """Return the selected text without changing a read-only widget."""
    try:
        if not widget.tag_ranges("sel"):
            return None
        return str(widget.get("sel.first", "sel.last"))
    except (AttributeError, base.tk.TclError):
        return None


def widget_is_editable(widget: Any) -> bool:
    """Return whether a Tk text widget accepts destructive clipboard actions."""
    try:
        return str(widget.cget("state")) != "disabled"
    except (AttributeError, base.tk.TclError):
        return False


def action_for_windows_keycode(keycode: int, *, editable: bool) -> ClipboardAction | None:
    """Map physical Windows Ctrl shortcuts, independent of keyboard layout."""
    action = WINDOWS_CTRL_KEYCODES.get(keycode)
    if action in {"cut", "paste"} and not editable:
        return None
    return action


class ClipboardOllamaChatApp(logged.LoggedOllamaChatApp):
    """Logged Ollama chat with explicit clipboard support for all text areas."""

    def __init__(self, *, log_file: Path) -> None:
        super().__init__(log_file=log_file)
        self._clipboard_target: Any | None = None
        self._text_widgets = (
            self.system_text,
            self.chat_text,
            self.input_text,
        )
        self._install_clipboard_bindings()
        self._install_application_menu()
        LOGGER.info("Clipboard support initialized widgets=%d", len(self._text_widgets))

    def _install_application_menu(self) -> None:
        menu = base.tk.Menu(self)

        self.edit_menu = base.tk.Menu(
            menu,
            tearoff=False,
            postcommand=self._refresh_edit_menu,
        )
        self.edit_menu.add_command(
            label="Вырезать",
            accelerator="Ctrl+X",
            command=self._cut,
        )
        self.edit_menu.add_command(
            label="Копировать",
            accelerator="Ctrl+C",
            command=self._copy,
        )
        self.edit_menu.add_command(
            label="Вставить",
            accelerator="Ctrl+V",
            command=self._paste,
        )
        self.edit_menu.add_separator()
        self.edit_menu.add_command(
            label="Выделить всё",
            accelerator="Ctrl+A",
            command=self._select_all,
        )
        menu.add_cascade(label="Правка", menu=self.edit_menu)

        diagnostics = base.tk.Menu(menu, tearoff=False)
        diagnostics.add_command(label="Открыть журналы", command=self._open_logs)
        diagnostics.add_command(label="Показать путь к журналу", command=self._show_log_path)
        menu.add_cascade(label="Диагностика", menu=diagnostics)

        self.context_menu = base.tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="Вырезать", command=self._cut)
        self.context_menu.add_command(label="Копировать", command=self._copy)
        self.context_menu.add_command(label="Вставить", command=self._paste)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Выделить всё", command=self._select_all)
        self.context_menu.add_command(
            label="Копировать весь диалог",
            command=self._copy_entire_chat,
        )

        self.configure(menu=menu)

    def _install_clipboard_bindings(self) -> None:
        for widget in self._text_widgets:
            widget.bind("<Button-3>", self._show_context_menu, add="+")
            widget.bind("<<Copy>>", self._copy_event, add="+")
            widget.bind("<<Cut>>", self._cut_event, add="+")
            widget.bind("<<Paste>>", self._paste_event, add="+")
            widget.bind("<<SelectAll>>", self._select_all_event, add="+")
            widget.bind("<Control-KeyPress>", self._control_key_event, add="+")
            widget.bind("<Control-Insert>", self._copy_event, add="+")
            widget.bind("<Shift-Insert>", self._paste_event, add="+")
            widget.bind("<Shift-Delete>", self._cut_event, add="+")

        for sequence in ("<Control-a>", "<Control-A>"):
            for widget in self._text_widgets:
                widget.bind(sequence, self._select_all_event, add="+")

    def _show_context_menu(self, event: Any) -> str:
        target = event.widget
        if target not in self._text_widgets:
            return "break"

        self._clipboard_target = target
        target.focus_set()
        self._refresh_context_menu(target)
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        return "break"

    def _refresh_edit_menu(self) -> None:
        target = self._resolve_target()
        self._set_menu_states(self.edit_menu, target, include_full_chat=False)

    def _refresh_context_menu(self, target: Any) -> None:
        self._set_menu_states(self.context_menu, target, include_full_chat=True)

    def _set_menu_states(
        self,
        menu: Any,
        target: Any | None,
        *,
        include_full_chat: bool,
    ) -> None:
        editable = target is not None and widget_is_editable(target)
        has_selection = target is not None and selected_text(target) is not None
        can_paste = editable and self._clipboard_has_text()

        menu.entryconfigure(0, state="normal" if editable and has_selection else "disabled")
        menu.entryconfigure(1, state="normal" if has_selection else "disabled")
        menu.entryconfigure(2, state="normal" if can_paste else "disabled")
        menu.entryconfigure(4, state="normal" if target is not None else "disabled")
        if include_full_chat:
            menu.entryconfigure(5, state="normal")

    def _resolve_target(self, widget: Any | None = None) -> Any | None:
        if widget in self._text_widgets:
            self._clipboard_target = widget
            return widget

        focused = self.focus_get()
        if focused in self._text_widgets:
            self._clipboard_target = focused
            return focused

        if self._clipboard_target in self._text_widgets:
            return self._clipboard_target
        return self.input_text

    def _clipboard_has_text(self) -> bool:
        try:
            return bool(self.clipboard_get())
        except base.tk.TclError:
            return False

    def _write_clipboard(self, text: str, *, source: str) -> bool:
        if not text:
            return False
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        LOGGER.info("Clipboard copy source=%s text=%s", source, logged.describe_text(text))
        self._show_clipboard_status("Текст скопирован")
        return True

    def _copy(self, widget: Any | None = None) -> bool:
        target = self._resolve_target(widget)
        text = selected_text(target) if target is not None else None
        if text is None:
            self.bell()
            self._show_clipboard_status("Сначала выделите текст")
            return False
        return self._write_clipboard(text, source=self._widget_name(target))

    def _cut(self, widget: Any | None = None) -> bool:
        target = self._resolve_target(widget)
        if target is None or not widget_is_editable(target):
            self.bell()
            return False
        if not self._copy(target):
            return False
        try:
            target.delete("sel.first", "sel.last")
        except base.tk.TclError:
            return False
        LOGGER.debug("Clipboard cut target=%s", self._widget_name(target))
        return True

    def _paste(self, widget: Any | None = None) -> bool:
        target = self._resolve_target(widget)
        if target is None or not widget_is_editable(target):
            self.bell()
            return False

        try:
            text = str(self.clipboard_get())
        except base.tk.TclError:
            self.bell()
            self._show_clipboard_status("Буфер обмена пуст")
            return False

        try:
            if target.tag_ranges("sel"):
                target.delete("sel.first", "sel.last")
            target.insert("insert", text)
            target.see("insert")
            target.focus_set()
        except base.tk.TclError:
            LOGGER.exception("Clipboard paste failed target=%s", self._widget_name(target))
            return False

        LOGGER.info(
            "Clipboard paste target=%s text=%s",
            self._widget_name(target),
            logged.describe_text(text),
        )
        self._show_clipboard_status("Текст вставлен")
        return True

    def _select_all(self, widget: Any | None = None) -> bool:
        target = self._resolve_target(widget)
        if target is None:
            return False
        try:
            target.tag_add("sel", "1.0", "end-1c")
            target.mark_set("insert", "end-1c")
            target.see("insert")
            target.focus_set()
        except base.tk.TclError:
            LOGGER.exception("Select all failed target=%s", self._widget_name(target))
            return False
        LOGGER.debug("Selected all text target=%s", self._widget_name(target))
        return True

    def _copy_entire_chat(self) -> bool:
        try:
            text = str(self.chat_text.get("1.0", "end-1c"))
        except base.tk.TclError:
            LOGGER.exception("Failed to read full chat for clipboard")
            return False
        return self._write_clipboard(text, source="chat_full")

    def _copy_event(self, event: Any) -> str:
        self._copy(event.widget)
        return "break"

    def _cut_event(self, event: Any) -> str:
        self._cut(event.widget)
        return "break"

    def _paste_event(self, event: Any) -> str:
        self._paste(event.widget)
        return "break"

    def _select_all_event(self, event: Any) -> str:
        self._select_all(event.widget)
        return "break"

    def _control_key_event(self, event: Any) -> str | None:
        target = event.widget
        action = action_for_windows_keycode(
            int(getattr(event, "keycode", 0)),
            editable=widget_is_editable(target),
        )
        if action is None:
            return None

        callbacks = {
            "copy": self._copy,
            "cut": self._cut,
            "paste": self._paste,
            "select_all": self._select_all,
        }
        callbacks[action](target)
        return "break"

    def _widget_name(self, widget: Any) -> str:
        if widget is self.chat_text:
            return "chat"
        if widget is self.input_text:
            return "input"
        if widget is self.system_text:
            return "system_prompt"
        return str(widget)

    def _show_clipboard_status(self, text: str) -> None:
        if not hasattr(self, "chat_status_var"):
            return
        self.chat_status_var.set(text)
        self.after(1800, self._restore_chat_status)

    def _restore_chat_status(self) -> None:
        if not self.winfo_exists() or self.generation_active:
            return
        self.chat_status_var.set("Enter — отправить · Shift+Enter — новая строка")


def main() -> None:
    args = logged.parse_arguments()
    log_file = logged.configure_logging(
        level_name=args.log_level,
        include_content=args.log_content,
        log_file=args.log_file,
    )
    logged.install_exception_hooks()
    LOGGER.info(
        "Application startup app=%s python=%s executable=%s platform=%s cwd=%s clipboard=true",
        logged.APP_TITLE,
        platform.python_version(),
        sys.executable,
        platform.platform(),
        Path.cwd(),
    )
    try:
        app = ClipboardOllamaChatApp(log_file=log_file)
        app.mainloop()
    except Exception:
        LOGGER.critical("Fatal application error", exc_info=True)
        raise
    finally:
        LOGGER.info("Application process is exiting")
        for handler in LOGGER.handlers:
            handler.flush()


if __name__ == "__main__":
    main()
