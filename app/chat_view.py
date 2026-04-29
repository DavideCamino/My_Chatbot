"""
ChatView — the right-hand message area.

Displays scrollable message bubbles (user right, assistant left),
a system-prompt editor panel, an input bar, and a Send/Stop button.

Usage
-----
  view = ChatView()
  view.load_chat(chat)           # populate from a Chat object
  view.set_callbacks(on_send=..., on_stop=...)
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Pango

from app.chat_store import Chat, Message


class MessageBubble(Gtk.Box):
    """
    A single message bubble with an optional copy button that appears on hover.
    """

    def __init__(self, role: str, content: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.role = role
        self._content = content

        is_user = role == "user"

        # Outer row: aligns the bubble left or right
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_halign(Gtk.Align.END if is_user else Gtk.Align.START)
        self.append(row)

        # The bubble frame
        frame = Gtk.Frame()
        frame.add_css_class("card")
        if is_user:
            frame.add_css_class("bubble-user")
        else:
            frame.add_css_class("bubble-assistant")
        row.append(frame)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_top(8)
        inner.set_margin_bottom(8)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        frame.set_child(inner)

        # Message label (selectable, wrapping)
        self._label = Gtk.Label(label=content)
        self._label.set_wrap(True)
        self._label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._label.set_selectable(True)
        self._label.set_xalign(0)
        self._label.set_max_width_chars(80)
        inner.append(self._label)

        # Copy button row (always visible for accessibility; subtle styling)
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_row.set_halign(Gtk.Align.END)
        inner.append(btn_row)

        self._copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        self._copy_btn.set_tooltip_text("Copy")
        self._copy_btn.add_css_class("flat")
        self._copy_btn.add_css_class("circular")
        self._copy_btn.set_has_frame(False)
        self._copy_btn.connect("clicked", self._on_copy)
        btn_row.append(self._copy_btn)

        self._copied_label = Gtk.Label(label="Copied!")
        self._copied_label.set_visible(False)
        self._copied_label.add_css_class("dim-label")
        btn_row.append(self._copied_label)

    def update_content(self, content: str):
        """Replace the label text (used during streaming)."""
        self._content = content
        self._label.set_label(content)

    def _on_copy(self, _btn):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self._content)
        # Show brief "Copied!" feedback
        self._copied_label.set_visible(True)
        GLib.timeout_add(1500, self._hide_copied)

    def _hide_copied(self):
        self._copied_label.set_visible(False)
        return GLib.SOURCE_REMOVE


class ChatView(Gtk.Box):
    """
    The main chat panel: system-prompt bar + scrollable message list + input bar.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._chat: Chat | None = None
        self._on_send = None        # callback(user_text: str)
        self._on_stop = None        # callback()
        self._streaming_bubble: MessageBubble | None = None
        self._streaming_text = ""

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        # ── System prompt collapsible ──────────────────────────────────
        expander = Gtk.Expander(label="System Prompt")
        expander.set_margin_start(12)
        expander.set_margin_end(12)
        expander.set_margin_top(6)
        self.append(expander)

        sp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sp_box.set_margin_top(4)
        expander.set_child(sp_box)

        self._system_prompt_view = Gtk.TextView()
        self._system_prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._system_prompt_view.set_size_request(-1, 72)
        self._system_prompt_view.add_css_class("card")
        sp_box.append(self._system_prompt_view)

        sp_save_btn = Gtk.Button(label="Save system prompt")
        sp_save_btn.set_halign(Gtk.Align.END)
        sp_save_btn.add_css_class("suggested-action")
        sp_save_btn.connect("clicked", self._on_save_system_prompt)
        sp_box.append(sp_save_btn)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Scrollable message list ────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scroll)

        self._msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._msg_box.set_margin_top(16)
        self._msg_box.set_margin_bottom(16)
        self._msg_box.set_margin_start(16)
        self._msg_box.set_margin_end(16)
        scroll.set_child(self._msg_box)

        # Keep a reference for auto-scrolling
        self._scroll = scroll
        self._vadj = scroll.get_vadjustment()

        # ── Input bar ─────────────────────────────────────────────────
        input_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_bar.set_margin_top(8)
        input_bar.set_margin_bottom(8)
        input_bar.set_margin_start(12)
        input_bar.set_margin_end(12)
        self.append(input_bar)

        # Multi-line input wrapped in a scrolled window
        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        input_scroll.set_max_content_height(120)
        input_scroll.set_propagate_natural_height(True)
        input_scroll.set_hexpand(True)
        input_scroll.add_css_class("card")
        input_bar.append(input_scroll)

        self._input = Gtk.TextView()
        self._input.set_wrap_mode(Gtk.WrapMode.WORD)
        self._input.set_accepts_tab(False)
        self._input.set_top_margin(8)
        self._input.set_bottom_margin(8)
        self._input.set_left_margin(10)
        self._input.set_right_margin(10)
        input_scroll.set_child(self._input)

        # Ctrl+Enter or plain Enter (no modifier) sends the message
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self._input.add_controller(key_ctrl)

        # Send / Stop button
        self._send_btn = Gtk.Button(label="Send")
        self._send_btn.add_css_class("suggested-action")
        self._send_btn.set_valign(Gtk.Align.END)
        self._send_btn.connect("clicked", self._on_send_clicked)
        input_bar.append(self._send_btn)

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def set_callbacks(self, on_send=None, on_stop=None):
        self._on_send = on_send
        self._on_stop = on_stop

    def load_chat(self, chat: Chat):
        """Clear the view and populate it from a Chat object."""
        self._chat = chat
        # Clear existing bubbles
        child = self._msg_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._msg_box.remove(child)
            child = nxt

        # System prompt
        buf = self._system_prompt_view.get_buffer()
        buf.set_text(chat.system_prompt)

        # Messages
        for msg in chat.messages:
            self._add_bubble(msg.role, msg.content)

        self._scroll_to_bottom()

    def append_user_message(self, text: str):
        self._add_bubble("user", text)
        self._scroll_to_bottom()

    def begin_streaming(self) -> MessageBubble:
        """Add an empty assistant bubble and return it for incremental updates."""
        bubble = self._add_bubble("assistant", "")
        self._streaming_bubble = bubble
        self._streaming_text = ""
        return bubble

    def append_token(self, token: str):
        """Append a token to the current streaming bubble."""
        if self._streaming_bubble:
            self._streaming_text += token
            self._streaming_bubble.update_content(self._streaming_text)
            self._scroll_to_bottom()

    def finish_streaming(self) -> str:
        """Mark streaming done and return the full assistant text."""
        text = self._streaming_text
        self._streaming_bubble = None
        self._streaming_text = ""
        return text

    def set_input_sensitive(self, sensitive: bool):
        self._input.set_sensitive(sensitive)
        if sensitive:
            self._send_btn.set_label("Send")
            self._send_btn.remove_css_class("destructive-action")
            self._send_btn.add_css_class("suggested-action")
        else:
            self._send_btn.set_label("Stop")
            self._send_btn.remove_css_class("suggested-action")
            self._send_btn.add_css_class("destructive-action")

    def clear_input(self):
        self._input.get_buffer().set_text("")

    def get_input_text(self) -> str:
        buf = self._input.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _add_bubble(self, role: str, content: str) -> MessageBubble:
        bubble = MessageBubble(role, content)
        self._msg_box.append(bubble)
        return bubble

    def _scroll_to_bottom(self):
        def _do_scroll():
            self._vadj.set_value(self._vadj.get_upper() - self._vadj.get_page_size())
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do_scroll)

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        # Enter without Shift sends the message
        if keyval == 65293:  # GDK_KEY_Return
            if not (state & Gdk.ModifierType.SHIFT_MASK):
                self._on_send_clicked(None)
                return True
        return False

    def _on_send_clicked(self, _btn):
        # If currently generating, this acts as Stop
        if not self._input.get_sensitive():
            if self._on_stop:
                self._on_stop()
            return

        text = self.get_input_text().strip()
        if not text:
            return
        self.clear_input()
        if self._on_send:
            self._on_send(text)

    def _on_save_system_prompt(self, _btn):
        if not self._chat:
            return
        buf = self._system_prompt_view.get_buffer()
        sp = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._chat.system_prompt = sp
        from app.chat_store import ChatStore
        ChatStore.save_chat(self._chat)