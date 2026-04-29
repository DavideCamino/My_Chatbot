"""
ChatView — the right-hand message area.

User bubbles: plain Gtk.Label (right-aligned).
Assistant bubbles: WebKit2 WebView rendering markdown as HTML (full width).

Dependencies (system packages):
  gir1.2-webkit2-4.1  (or webkit2gtk-4.1 on Fedora/Arch)
  python3-mistune      OR  pip install mistune
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")   # WebKitGTK 6 (GTK4)
from gi.repository import Gtk, Adw, Gdk, GLib, Pango, WebKit

import mistune   # pip install mistune

from app.chat_store import Chat, Message


# ── Markdown → HTML ────────────────────────────────────────────────────────

_md = mistune.create_markdown(plugins=["strikethrough", "table", "task_lists"])

# Minimal CSS injected into every WebView so it matches the GNOME theme
_CSS_LIGHT = """
body { font-family: sans-serif; font-size: 15px; line-height: 1.6;
       color: #1a1a1a; background: transparent; margin: 0; padding: 4px 0; }
code, pre { font-family: monospace; background: #f0f0f0;
            border-radius: 4px; font-size: 13px; }
pre { padding: 10px; overflow-x: auto; }
code { padding: 2px 5px; }
blockquote { border-left: 3px solid #aaa; margin: 0; padding-left: 12px; color: #555; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 4px 8px; }
th { background: #f5f5f5; }
a { color: #1c6ea4; }
p:first-child { margin-top: 0; } p:last-child { margin-bottom: 0; }
"""

_CSS_DARK = """
body { font-family: sans-serif; font-size: 15px; line-height: 1.6;
       color: #e0e0e0; background: transparent; margin: 0; padding: 4px 0; }
code, pre { font-family: monospace; background: #2a2a2a;
            border-radius: 4px; font-size: 13px; }
pre { padding: 10px; overflow-x: auto; }
code { padding: 2px 5px; }
blockquote { border-left: 3px solid #666; margin: 0; padding-left: 12px; color: #aaa; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #555; padding: 4px 8px; }
th { background: #333; }
a { color: #6aaddb; }
p:first-child { margin-top: 0; } p:last-child { margin-bottom: 0; }
"""


def _is_dark() -> bool:
    """Detect whether the system is using a dark colour scheme."""
    style = Gtk.Settings.get_default()
    return style.get_property("gtk-application-prefer-dark-theme")


def _md_to_html(text: str) -> str:
    css = _CSS_DARK if _is_dark() else _CSS_LIGHT
    body = _md(text) if text.strip() else "<p></p>"
    return (
        f"<html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head>"
        f"<body>{body}</body></html>"
    )


# ── WebView bubble for assistant messages ──────────────────────────────────

_MIN_WV_HEIGHT = 40   # px — prevent zero-height flicker on first load

class AssistantBubble(Gtk.Box):
    """
    Full-width assistant bubble backed by a WebKit WebView.
    Height is auto-sized via JS after each content update.
    """

    def __init__(self, content: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_hexpand(True)
        self._content = content

        frame = Gtk.Frame()
        frame.add_css_class("card")
        frame.set_hexpand(True)
        self.append(frame)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        inner.set_margin_top(8)
        inner.set_margin_bottom(8)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        inner.set_hexpand(True)
        frame.set_child(inner)

        # WebView — transparent background, no scrollbars
        self._wv = WebKit.WebView()
        self._wv.set_hexpand(True)
        self._wv.set_size_request(-1, _MIN_WV_HEIGHT)
        self._wv.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        # Disable context menu & navigation
        self._wv.connect("decide-policy", lambda wv, d, t: d.ignore())
        inner.append(self._wv)

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

        # Load initial content
        self._load_content(content)

    def update_content(self, content: str):
        self._content = content
        self._load_content(content)

    def _load_content(self, content: str):
        html = _md_to_html(content)
        self._wv.load_html(html, "about:blank")
        # After load, measure real body height and resize the widget
        self._wv.connect("load-changed", self._on_load_changed)

    def _on_load_changed(self, wv, event):
        if event == WebKit.LoadEvent.FINISHED:
            # Query the document's scroll height via JS and resize
            wv.evaluate_javascript(
                "document.body.scrollHeight",
                -1, None, None, None,
                self._on_height_result,
                None,
            )

    def _on_height_result(self, wv, result, _user_data):
        try:
            js_val = wv.evaluate_javascript_finish(result)
            h = int(js_val.to_double())
            if h > 0:
                wv.set_size_request(-1, max(h, _MIN_WV_HEIGHT))
        except Exception:
            pass

    def _on_copy(self, _btn):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self._content)
        self._copied_lbl.set_visible(True)
        GLib.timeout_add(1500, lambda: self._copied_lbl.set_visible(False) or GLib.SOURCE_REMOVE)


# ── Plain label bubble for user messages ──────────────────────────────────

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
        if role == "assistant":
            bubble = AssistantBubble(content)
        else:
            bubble = UserBubble(content)
        self._msg_box.append(bubble)
        return bubble

    def _scroll_to_bottom(self):
        def _do():
            self._vadj.set_value(self._vadj.get_upper() - self._vadj.get_page_size())
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do)

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == 65293:  # Return
            from gi.repository import Gdk
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