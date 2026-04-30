"""
ChatView — the right-hand message area.

Rendering strategy
------------------
Each assistant message is split into alternating segments:
  • TextSegment  — rendered with a Gtk.TextView + Pango markup (markdown)
  • CodeSegment  — rendered with a monospace Gtk.TextView inside a dark
                   rounded box, with a language label and a Copy button.

Segments are rebuilt from scratch on every token during streaming,
so code blocks appear and grow in real time just like normal text.

Dependencies: pip install mistune  (only used for inline markdown in text segments)
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Pango

import html as _html
import re
from dataclasses import dataclass, field
from typing import List

from app.chat_store import Chat, Message


# ── Markdown inline → Pango markup (text segments only) ──────────────────

def _inline_md(text: str) -> str:
    result = []
    i = 0
    s = text
    while i < len(s):
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
        if s[i:i+3] == '***':
            j = s.find('***', i + 3)
            if j != -1:
                result.append(f'<b><i>{_html.escape(s[i+3:j])}</i></b>')
                i = j + 3
                continue
        if s[i:i+2] in ('**', '__'):
            marker = s[i:i+2]
            j = s.find(marker, i + 2)
            if j != -1:
                result.append(f'<b>{_html.escape(s[i+2:j])}</b>')
                i = j + 2
                continue
        if s[i] in ('*', '_'):
            marker = s[i]
            j = s.find(marker, i + 1)
            if j != -1:
                result.append(f'<i>{_html.escape(s[i+1:j])}</i>')
                i = j + 1
                continue
        result.append(_html.escape(s[i]))
        i += 1
    return "".join(result)


def _line_to_pango(line: str) -> str:
    """Convert one markdown line to a Pango markup string."""
    m = re.match(r"^(#{1,3})\s+(.*)", line)
    if m:
        sizes = {1: "x-large", 2: "large", 3: "medium"}
        return f'<span size="{sizes[len(m.group(1))]}" weight="bold">{_inline_md(m.group(2))}</span>'
    if re.match(r"^[-*_]{3,}\s*$", line):
        return '<span foreground="#888">────────────────────</span>'
    if line.startswith("> "):
        return f'<span foreground="#888">┃ {_inline_md(line[2:])}</span>'
    m = re.match(r"^[\-\*\+]\s+(.*)", line)
    if m:
        return f"  • {_inline_md(m.group(1))}"
    m = re.match(r"^(\d+)\.\s+(.*)", line)
    if m:
        return f"  {m.group(1)}. {_inline_md(m.group(2))}"
    return _inline_md(line)


def _text_to_pango(text: str) -> str:
    return "\n".join(_line_to_pango(l) for l in text.split("\n"))


# ── Segment dataclasses ───────────────────────────────────────────────────

@dataclass
class TextSeg:
    text: str = ""          # raw markdown text

@dataclass
class CodeSeg:
    lang: str = ""          # language hint (may be empty)
    code: str = ""          # code content (may be partial / no closing ```)
    closed: bool = False    # True once the closing ``` has been seen


def _parse_segments(raw: str) -> List:
    """
    Split raw markdown into alternating TextSeg / CodeSeg objects.
    Works on partial input (no closing ``` required).
    """
    segments: List = []
    cur_text = []
    lines = raw.split("\n")
    in_code = False
    lang = ""
    cur_code: List[str] = []

    for line in lines:
        if not in_code:
            if line.startswith("```"):
                # flush text
                if cur_text:
                    segments.append(TextSeg("\n".join(cur_text)))
                    cur_text = []
                lang = line[3:].strip()
                in_code = True
                cur_code = []
            else:
                cur_text.append(line)
        else:
            if line.startswith("```"):
                segments.append(CodeSeg(lang=lang, code="\n".join(cur_code), closed=True))
                in_code = False
                lang = ""
                cur_code = []
            else:
                cur_code.append(line)

    # flush remaining
    if in_code:
        # partial (unclosed) code block — still show it
        segments.append(CodeSeg(lang=lang, code="\n".join(cur_code), closed=False))
    elif cur_text:
        segments.append(TextSeg("\n".join(cur_text)))

    return segments


# ── CodeBlock widget ──────────────────────────────────────────────────────

class CodeBlock(Gtk.Box):
    """
    A dark rounded box containing:
      • top bar: language label  +  Copy button
      • monospace TextView with the code
    """
    def __init__(self, lang: str, code: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_hexpand(True)
        self.add_css_class("code-block-box")
        self._code = code

        # ── Top bar ──────────────────────────────────────────────
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        top.add_css_class("code-block-topbar")
        top.set_margin_start(10)
        top.set_margin_end(6)
        top.set_margin_top(4)
        top.set_margin_bottom(4)
        self.append(top)

        lang_lbl = Gtk.Label(label=lang or "code")
        lang_lbl.set_xalign(0)
        lang_lbl.set_hexpand(True)
        lang_lbl.add_css_class("dim-label")
        lang_lbl.set_css_classes(["caption", "dim-label"])
        top.append(lang_lbl)

        self._copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        self._copy_btn.set_tooltip_text("Copy code")
        self._copy_btn.add_css_class("flat")
        self._copy_btn.add_css_class("circular")
        self._copy_btn.connect("clicked", self._on_copy)
        top.append(self._copy_btn)

        self._copied_lbl = Gtk.Label(label="Copied!")
        self._copied_lbl.set_visible(False)
        self._copied_lbl.add_css_class("dim-label")
        top.append(self._copied_lbl)

        # ── Separator ────────────────────────────────────────────
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Code TextView ────────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroll.set_hexpand(True)
        self.append(scroll)

        self._tv = Gtk.TextView()
        self._tv.set_editable(False)
        self._tv.set_cursor_visible(False)
        self._tv.set_wrap_mode(Gtk.WrapMode.NONE)   # horizontal scroll for long lines
        self._tv.set_hexpand(True)
        self._tv.set_can_focus(False)
        self._tv.set_top_margin(10)
        self._tv.set_bottom_margin(10)
        self._tv.set_left_margin(12)
        self._tv.set_right_margin(12)
        self._tv.add_css_class("code-block-textview")
        scroll.set_child(self._tv)

        # Apply monospace tag
        buf = self._tv.get_buffer()
        self._mono_tag = buf.create_tag("mono", family="monospace", size_points=12)

        self.set_code(code)

    def set_code(self, code: str):
        self._code = code
        buf = self._tv.get_buffer()
        buf.set_text(code)
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        buf.apply_tag(self._mono_tag, start, end)

    def _on_copy(self, _btn):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self._code)
        self._copied_lbl.set_visible(True)
        GLib.timeout_add(1500, lambda: self._copied_lbl.set_visible(False) or GLib.SOURCE_REMOVE)


# ── AssistantBubble ───────────────────────────────────────────────────────

class AssistantBubble(Gtk.Box):
    """
    Full-width assistant bubble.

    Segments are updated IN PLACE to avoid layout glitching:
    - Existing TextSegment TextViews have their buffer replaced.
    - Existing CodeBlock widgets have set_code() called.
    - New widgets are only appended when the segment count grows.
    - Widgets are never removed during streaming.
    """
    def __init__(self, content: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_hexpand(True)
        self._content = content
        # Parallel list of live widgets matching the last parsed segments
        self._seg_widgets: list = []   # Gtk.TextView | CodeBlock

        outer_frame = Gtk.Frame()
        outer_frame.add_css_class("card")
        outer_frame.set_hexpand(True)
        self.append(outer_frame)

        self._outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._outer.set_margin_top(8)
        self._outer.set_margin_bottom(4)
        self._outer.set_margin_start(12)
        self._outer.set_margin_end(12)
        self._outer.set_hexpand(True)
        outer_frame.set_child(self._outer)

        self._seg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._seg_box.set_hexpand(True)
        self._outer.append(self._seg_box)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_row.set_halign(Gtk.Align.END)
        self._outer.append(btn_row)

        copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_btn.set_tooltip_text("Copy full response")
        copy_btn.add_css_class("flat")
        copy_btn.add_css_class("circular")
        copy_btn.connect("clicked", self._on_copy_all)
        btn_row.append(copy_btn)

        self._copied_lbl = Gtk.Label(label="Copied!")
        self._copied_lbl.set_visible(False)
        self._copied_lbl.add_css_class("dim-label")
        btn_row.append(self._copied_lbl)

        if content:
            self.update_content(content)

    # ------------------------------------------------------------------ #

    def update_content(self, content: str):
        self._content = content
        segments = _parse_segments(content)

        for i, seg in enumerate(segments):
            if i < len(self._seg_widgets):
                # Update existing widget in place
                w = self._seg_widgets[i]
                if isinstance(seg, TextSeg) and isinstance(w, Gtk.TextView):
                    self._set_textview(w, seg.text)
                elif isinstance(seg, CodeSeg) and isinstance(w, CodeBlock):
                    w.set_code(seg.code)
                else:
                    # Segment type changed (shouldn't happen mid-stream, but handle it)
                    self._seg_box.remove(w)
                    new_w = self._make_widget(seg)
                    # Insert at position i: append all then re-insert is complex in GTK4,
                    # so just replace via remove + append (only happens on type switch)
                    self._seg_widgets[i] = new_w
                    self._seg_box.append(new_w)
            else:
                # New segment — append a fresh widget
                w = self._make_widget(seg)
                self._seg_widgets.append(w)
                self._seg_box.append(w)

        # If the segment count shrank (shouldn't during streaming, but be safe)
        while len(self._seg_widgets) > len(segments):
            w = self._seg_widgets.pop()
            self._seg_box.remove(w)

    # ------------------------------------------------------------------ #

    def _make_widget(self, seg):
        if isinstance(seg, TextSeg):
            tv = self._new_textview()
            self._set_textview(tv, seg.text)
            return tv
        else:
            return CodeBlock(seg.lang, seg.code)

    def _new_textview(self) -> Gtk.TextView:
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_cursor_visible(False)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_hexpand(True)
        tv.set_can_focus(False)
        tv.add_css_class("transparent-textview")
        return tv

    def _set_textview(self, tv: Gtk.TextView, text: str):
        """Replace the buffer content of an existing TextView without recreating it."""
        buf = tv.get_buffer()
        buf.delete(buf.get_start_iter(), buf.get_end_iter())
        markup = _text_to_pango(text)
        buf.insert_markup(buf.get_start_iter(), markup, -1)

    def _on_copy_all(self, _btn):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self._content)
        self._copied_lbl.set_visible(True)
        GLib.timeout_add(1500, lambda: self._copied_lbl.set_visible(False) or GLib.SOURCE_REMOVE)


# ── UserBubble ────────────────────────────────────────────────────────────

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


# ── ChatView ──────────────────────────────────────────────────────────────

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
        provider = Gtk.CssProvider()
        provider.load_from_string("""
            textview.transparent-textview,
            textview.transparent-textview > text {
                background-color: transparent;
            }
            .code-block-box {
                background-color: #1e1e2e;
                border-radius: 8px;
            }
            .code-block-topbar {
                background-color: #2a2a3e;
                border-radius: 8px 8px 0 0;
            }
            textview.code-block-textview,
            textview.code-block-textview > text {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border-radius: 0 0 8px 8px;
            }
        """)
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