"""
Sidebar — the left panel listing all conversations.

Emits:
  on_chat_selected(chat_id: str)
  on_new_chat()
  on_delete_chat(chat_id: str)
  on_rename_chat(chat_id: str, new_title: str)
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from app.chat_store import Chat, ChatStore
from datetime import datetime, timezone


def _format_date(iso: str) -> str:
    """Return a human-friendly date string relative to now."""
    try:
        dt = datetime.fromisoformat(iso)
        now = datetime.now(timezone.utc)
        delta = now - dt.astimezone(timezone.utc)
        if delta.days == 0:
            return "Today"
        elif delta.days == 1:
            return "Yesterday"
        elif delta.days < 7:
            return f"{delta.days} days ago"
        else:
            return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


class ChatRow(Gtk.ListBoxRow):
    """A single row in the sidebar list."""

    def __init__(self, chat: Chat):
        super().__init__()
        self.chat_id = chat.id
        self._build(chat)

    def _build(self, chat: Chat):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(8)
        self.set_child(box)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        box.append(text_box)

        self._title_label = Gtk.Label(label=chat.title)
        self._title_label.set_xalign(0)
        self._title_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        self._title_label.set_max_width_chars(28)
        text_box.append(self._title_label)

        date_lbl = Gtk.Label(label=_format_date(chat.last_updated()))
        date_lbl.set_xalign(0)
        date_lbl.add_css_class("dim-label")
        date_lbl.set_css_classes(["caption", "dim-label"])
        text_box.append(date_lbl)

        # Context menu button
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("view-more-symbolic")
        menu_btn.add_css_class("flat")
        menu_btn.set_valign(Gtk.Align.CENTER)
        box.append(menu_btn)

        menu = Gtk.PopoverMenu.new_from_model(self._build_menu())
        menu_btn.set_popover(menu)

    def _build_menu(self) -> Gtk.Menu:
        #menu = Gtk.Menu.new()  # will use Gio.Menu instead
        from gi.repository import Gio
        gm = Gio.Menu()
        gm.append("Rename", f"row.rename::{self.chat_id}")
        gm.append("Delete", f"row.delete::{self.chat_id}")
        return gm

    def update_title(self, title: str):
        self._title_label.set_label(title)


class Sidebar(Gtk.Box):
    """
    The sidebar containing a New Chat button and a list of past conversations.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.on_chat_selected = None
        self.on_new_chat = None
        self.on_delete_chat = None
        self.on_rename_chat = None

        self._rows: dict[str, ChatRow] = {}  # chat_id -> ChatRow

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        # Header
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Gtk.Label(label="Chats"))
        self.append(header)

        new_btn = Gtk.Button(label="New Chat")
        new_btn.add_css_class("suggested-action")
        new_btn.connect("clicked", lambda _: self.on_new_chat and self.on_new_chat())
        header.pack_start(new_btn)

        # Search bar
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search…")
        self._search_entry.set_margin_start(8)
        self._search_entry.set_margin_end(8)
        self._search_entry.set_margin_top(6)
        self._search_entry.set_margin_bottom(4)
        self._search_entry.connect("search-changed", self._on_search_changed)
        self.append(self._search_entry)

        # Scrollable list
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scroll)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("navigation-sidebar")
        self._list_box.connect("row-activated", self._on_row_activated)
        self._list_box.set_filter_func(self._filter_func)
        scroll.set_child(self._list_box)

        self._search_query = ""

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def refresh(self):
        """Reload all chats from disk and rebuild the list."""
        # Remove existing rows
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt
        self._rows.clear()

        for chat in ChatStore.list_chats():
            row = ChatRow(chat)
            self._list_box.append(row)
            self._rows[chat.id] = row

    def select_chat(self, chat_id: str):
        """Highlight the row for the given chat."""
        row = self._rows.get(chat_id)
        if row:
            self._list_box.select_row(row)

    def update_chat_title(self, chat_id: str, title: str):
        row = self._rows.get(chat_id)
        if row:
            row.update_title(title)

    def prepend_chat(self, chat):
        """Add a newly created chat to the top of the list."""
        row = ChatRow(chat)
        self._list_box.prepend(row)
        self._rows[chat.id] = row
        self._list_box.select_row(row)

    def remove_chat(self, chat_id: str):
        row = self._rows.pop(chat_id, None)
        if row:
            self._list_box.remove(row)

    # ------------------------------------------------------------------ #
    # Event handlers
    # ------------------------------------------------------------------ #

    def _on_row_activated(self, _lb, row: ChatRow):
        if self.on_chat_selected:
            self.on_chat_selected(row.chat_id)

    def _on_search_changed(self, entry):
        self._search_query = entry.get_text().lower()
        self._list_box.invalidate_filter()

    def _filter_func(self, row: ChatRow) -> bool:
        if not self._search_query:
            return True
        return self._search_query in row._title_label.get_label().lower()