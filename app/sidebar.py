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

    def __init__(self, chat: Chat, on_delete, on_rename):
        super().__init__()
        self.chat_id = chat.id
        self._on_delete = on_delete
        self._on_rename = on_rename
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
        date_lbl.set_css_classes(["caption", "dim-label"])
        text_box.append(date_lbl)

        # Context menu button — plain Gtk.Button with a Popover
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("view-more-symbolic")
        menu_btn.add_css_class("flat")
        menu_btn.set_valign(Gtk.Align.CENTER)
        box.append(menu_btn)

        # Build popover with real buttons instead of Gio.Menu actions
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pop_box.set_margin_top(4)
        pop_box.set_margin_bottom(4)
        pop_box.set_margin_start(4)
        pop_box.set_margin_end(4)

        rename_btn = Gtk.Button(label="Rename")
        rename_btn.add_css_class("flat")
        rename_btn.connect("clicked", self._do_rename, menu_btn)
        pop_box.append(rename_btn)

        delete_btn = Gtk.Button(label="Delete")
        delete_btn.add_css_class("flat")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self._do_delete, menu_btn)
        pop_box.append(delete_btn)

        popover = Gtk.Popover()
        popover.set_child(pop_box)
        menu_btn.set_popover(popover)

    def _do_delete(self, _btn, menu_btn):
        menu_btn.get_popover().popdown()
        if self._on_delete:
            self._on_delete(self.chat_id)

    def _do_rename(self, _btn, menu_btn):
        menu_btn.get_popover().popdown()
        # Show an inline rename dialog
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="Rename chat",
        )
        entry = Gtk.Entry()
        entry.set_text(self._title_label.get_label())
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.connect("response", self._on_rename_response, entry)
        dialog.present()

    def _on_rename_response(self, dialog, response, entry):
        if response == "rename":
            new_title = entry.get_text().strip()
            if new_title and self._on_rename:
                self._on_rename(self.chat_id, new_title)

    def update_title(self, title: str):
        self._title_label.set_label(title)


class Sidebar(Gtk.Box):
    """
    Sidebar: New Chat button + searchable list of past conversations.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.on_chat_selected = None
        self.on_new_chat = None
        self.on_delete_chat = None
        self.on_rename_chat = None

        self._rows: dict[str, ChatRow] = {}

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Gtk.Label(label="Chats"))
        self.append(header)

        new_btn = Gtk.Button(label="New Chat")
        new_btn.add_css_class("suggested-action")
        new_btn.connect("clicked", lambda _: self.on_new_chat and self.on_new_chat())
        header.pack_start(new_btn)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search…")
        self._search_entry.set_margin_start(8)
        self._search_entry.set_margin_end(8)
        self._search_entry.set_margin_top(6)
        self._search_entry.set_margin_bottom(4)
        self._search_entry.connect("search-changed", self._on_search_changed)
        self.append(self._search_entry)

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
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt
        self._rows.clear()

        for chat in ChatStore.list_chats():
            self._append_row(chat)

    def select_chat(self, chat_id: str):
        row = self._rows.get(chat_id)
        if row:
            self._list_box.select_row(row)

    def update_chat_title(self, chat_id: str, title: str):
        row = self._rows.get(chat_id)
        if row:
            row.update_title(title)

    def prepend_chat(self, chat: Chat):
        row = ChatRow(chat, self._handle_delete, self._handle_rename)
        self._list_box.prepend(row)
        self._rows[chat.id] = row
        self._list_box.select_row(row)

    def remove_chat(self, chat_id: str):
        row = self._rows.pop(chat_id, None)
        if row:
            self._list_box.remove(row)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _append_row(self, chat: Chat):
        row = ChatRow(chat, self._handle_delete, self._handle_rename)
        self._list_box.append(row)
        self._rows[chat.id] = row

    def _handle_delete(self, chat_id: str):
        if self.on_delete_chat:
            self.on_delete_chat(chat_id)

    def _handle_rename(self, chat_id: str, new_title: str):
        if self.on_rename_chat:
            self.on_rename_chat(chat_id, new_title)

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