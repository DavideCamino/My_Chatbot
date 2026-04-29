"""
ChatView — the right-hand message area.

User bubbles:     plain Gtk.Label (right-aligned).
Assistant bubbles: Gtk.TextView with Pango markup rendered from markdown.
                   Full-width, stable during streaming, no WebKit needed.

Extra dependency: pip install mistune
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Pango

import html as _html
import re

from app.chat_store import Chat, Message


# ── Markdown → Pango markup ────────────────────────────────────────────────
# We do a lightweight manual conversion rather than mistune so there are
# zero extra dependencies and the result maps cleanly to Pango tags.

def _md_to_pango(text: str) -> str:
    """
    Convert a small but practical subset of Markdown to Pango markup.
    Handles: headings, bold, italic, inline code, code blocks,
             unordered lists, ordered lists, blockquotes, horizontal rules.
    """
    lines = text.split("\n")
    out = []
    in_code_block = False
    code_buf = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── fenced code block ──────────────────────────────────────
        if line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_buf = []
            else:
                in_code_block = False
                code = "\n".join(code_buf)
                escaped = _html.escape(code)
                out.append(
                    f'<span font_family="monospace" size="small" '
                    f'background="#2a2a2a" foreground="#e0e0e0"> {escaped} </span>'
                )
            i += 1
            continue

        if in_code_block:
            code_buf.append(line)
            i += 1
            continue

        # ── headings ───────────────────────────────────────────────
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            sizes = {1: "x-large", 2: "large", 3: "medium"}
            content = _inline_md(m.group(2))
            out.append(f'<span size="{sizes[level]}" weight="bold">{content}</span>')
            i += 1
            continue

        # ── horizontal rule ────────────────────────────────────────
        if re.match(r"^[-*_]{3,}\s*$", line):
            out.append('<span foreground="#888">────────────────────</span>')
            i += 1
            continue

        # ── blockquote ─────────────────────────────────────────────
        if line.startswith("> "):
            content = _inline_md(line[2:])
            out.append(f'<span foreground="#888">┃ {content}</span>')
            i += 1
            continue

        # ── unordered list ─────────────────────────────────────────
        m = re.match(r"^[\-\*\+]\s+(.*)", line)
        if m:
            content = _inline_md(m.group(1))
            out.append(f"  • {content}")
            i += 1
            continue

        # ── ordered list ───────────────────────────────────────────
        m = re.match(r"^(\d+)\.\s+(.*)", line)
        if m:
            content = _inline_md(m.group(2))
            out.append(f"  {m.group(1)}. {content}")
            i += 1
            continue

        # ── blank line ─────────────────────────────────────────────
        if line.strip() == "":
            out.append("")
            i += 1
            continue

        # ── normal paragraph line ──────────────────────────────────
        out.append(_inline_md(line))
        i += 1

    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Apply inline markdown (bold, italic, inline code) to a single line."""
    # Escape XML special chars first, but preserve the raw text for processing
    # We work on a character level so we can escape and then apply markup.
    # Strategy: tokenise by backtick/asterisk/underscore spans.

    result = []
    i = 0
    s = text

    while i < len(s):
        # inline code: `...`
        if s[i] == '`':
            j = s.find('`', i + 1)
            if j != -1:
                code = _html.escape(s[i+1:j])
                result.append(
                    f'<span font_family="monospace" size="small"'
                    f' background="#333" foreground="#e8e8e8"> {code} </span>'
                )
                i = j + 1
                continue

        # bold+italic: ***...***
        if s[i:i+3] == '***':
            j = s.find('***', i + 3)
            if j != -1:
                inner = _html.escape(s[i+3:j])
                result.append(f'<b><i>{inner}</i></b>')
                i = j + 3
                continue

        # bold: **...** or __...__
        if s[i:i+2] in ('**', '__'):
            marker = s[i:i+2]
            j = s.find(marker, i + 2)
            if j != -1:
                inner = _html.escape(s[i+2:j])
                result.append(f'<b>{inner}</b>')
                i = j + 2
                continue

        # italic: *...* or _..._
        if s[i] in ('*', '_'):
            marker = s[i]
            j = s.find(marker, i + 1)
            if j != -1:
                inner = _html.escape(s[i+1:j])
                result.append(f'<i>{inner}</i>')
                i = j + 1
                continue

        # normal char — escape for Pango XML
        result.append(_html.escape(s[i]))
        i += 1

    return "".join(result)


# ── Assistant bubble ───────────────────────────────────────────────────────

class AssistantBubble(Gtk.Box):
    """Full-width assistant bubble using a non-editable Gtk.TextView."""

    def __init__(self, content: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_hexpand(True)
        self._content = content

        frame = Gtk.Frame()
        frame.add_css_class("card")
        frame.set_hexpand(True)
        self.append(frame)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_top(8)
        inner.set_margin_bottom(8)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        inner.set_hexpand(True)
        frame.set_child(inner)

        # TextView — non-editable, no cursor, wraps, full width
        self._tv = Gtk.TextView()
        self._tv.set_editable(False)
        self._tv.set_cursor_visible(False)
        self._tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._tv.set_hexpand(True)
        self._tv.set_can_focus(False)
        # Make background transparent so the card frame shows through
        self._tv.add_css_class("transparent-textview")
        inner.append(self._tv)

        # Copy button row
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_row.set_halign(Gtk.Align.END)
        inner.append(btn_row)

        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.set_tooltip_text("Copy")
        copy_btn.add_css_class("flat")
        copy_btn.add_css_class("circular")
        copy_btn.connect("clicked", self._on_copy)
        btn_row.append(copy_btn)

        self._copied_lbl = Gtk.Label(label="Copied!")
        self._copied_lbl.set_visible(False)
        self._copied_lbl.add_css_class("dim-label")
        btn_row.append(self._copied_lbl)

        if content:
            self.update_content(content)

    def update_content(self, content: str):
        self._content = content
        markup = _md_to_pango(content)
        buf = self._tv.get_buffer()
        buf.delete(buf.get_start_iter(), buf.get_end_iter())
        # insert_markup requires start iter
        buf.insert_markup(buf.get_start_iter(), markup, -1)

    def _on_copy(self, _btn):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self._content)
        self._copied_lbl.set_visible(True)
        GLib.timeout_add(1500, lambda: self._copied_lbl.set_visible(False) or GLib.SOURCE_REMOVE)


# ── User bubble ────────────────────────────────────────────────────────────

class UserBubble(Gtk.Box):
    def __init__(self, content: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._content = content

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_halign(Gtk.Align.END)
        self.append(row)

        frame = Gtk.Frame()
        frame.add_css_class("card")
        row.append(frame)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_top(8)
        inner.set_margin_bottom(8)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        frame.set_child(inner)

        lbl = Gtk.Label(label=content)
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_selectable(True)
        lbl.set_xalign(0)
        lbl.set_max_width_chars(72)
        inner.append(lbl)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_row.set_halign(Gtk.Align.END)
        inner.append(btn_row)

        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.set_tooltip_text("Copy")
        copy_btn.add_css_class("flat")
        copy_btn.add_css_class("circular")
        copy_btn.connect("clicked", self._on_copy)
        btn_row.append(copy_btn)

        self._copied_lbl = Gtk.Label(label="Copied!")
        self._copied_lbl.set_visible(False)
        self._copied_lbl.add_css_class("dim-label")
        btn_row.append(self._copied_lbl)

    def _on_copy(self, _btn):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self._content)
        self._copied_lbl.set_visible(True)
        GLib.timeout_add(1500, lambda: self._copied_lbl.set_visible(False) or GLib.SOURCE_REMOVE)


# ── Main ChatView ──────────────────────────────────────────────────────────

class ChatView(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._chat: Chat | None = None
        self._on_send = None
        self._on_stop = None
        self._streaming_bubble: AssistantBubble | None = None
        self._streaming_text = ""

        self._build_ui()
        self._inject_css()

    def _inject_css(self):
        """Make TextView backgrounds transparent so card styling shows through."""
        provider = Gtk.CssProvider()
        provider.load_from_string(
            "textview.transparent-textview, "
            "textview.transparent-textview > text { "
            "  background-color: transparent; "
            "}"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_ui(self):
        # System prompt expander
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

        # Scrollable message list
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scroll)

        self._msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._msg_box.set_margin_top(16)
        self._msg_box.set_margin_bottom(16)
        self._msg_box.set_margin_start(16)
        self._msg_box.set_margin_end(16)
        self._msg_box.set_hexpand(True)
        scroll.set_child(self._msg_box)

        self._scroll = scroll
        self._vadj = scroll.get_vadjustment()

        # Input bar
        input_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_bar.set_margin_top(8)
        input_bar.set_margin_bottom(8)
        input_bar.set_margin_start(12)
        input_bar.set_margin_end(12)
        self.append(input_bar)

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

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self._input.add_controller(key_ctrl)

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
        self._chat = chat
        child = self._msg_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._msg_box.remove(child)
            child = nxt

        buf = self._system_prompt_view.get_buffer()
        buf.set_text(chat.system_prompt)

        for msg in chat.messages:
            self._add_bubble(msg.role, msg.content)

        self._scroll_to_bottom()

    def append_user_message(self, text: str):
        self._add_bubble("user", text)
        self._scroll_to_bottom()

    def begin_streaming(self) -> AssistantBubble:
        bubble = AssistantBubble("")
        self._msg_box.append(bubble)
        self._streaming_bubble = bubble
        self._streaming_text = ""
        return bubble

    def append_token(self, token: str):
        if self._streaming_bubble:
            self._streaming_text += token
            self._streaming_bubble.update_content(self._streaming_text)
            self._scroll_to_bottom()

    def finish_streaming(self) -> str:
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

    def _add_bubble(self, role: str, content: str):
        bubble = AssistantBubble(content) if role == "assistant" else UserBubble(content)
        self._msg_box.append(bubble)
        return bubble

    def _scroll_to_bottom(self):
        def _do():
            self._vadj.set_value(self._vadj.get_upper() - self._vadj.get_page_size())
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do)

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == 65293:
            if not (state & Gdk.ModifierType.SHIFT_MASK):
                self._on_send_clicked(None)
                return True
        return False

    def _on_send_clicked(self, _btn):
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