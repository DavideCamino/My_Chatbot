"""
Sidebar — left panel listing all conversations.

Layout (top → bottom):
  • AdwHeaderBar  (title + ⋮ menu for multi-select actions)
  • SearchEntry
  • ScrolledWindow → ListBox  (the chat rows)
  • "New Chat" button          (pinned at the bottom)

Multi-select mode
-----------------
Clicking "Select" in the ⋮ menu switches the list into checkbox mode.
Each row grows a checkbox on the left. A bottom action bar appears with
"Delete selected" and "Cancel". "Select all / Deselect all" is also in
the ⋮ menu and toggles between the two states.

Callbacks (set by window.py)
-----------------------------
  on_chat_selected(chat_id)
  on_new_chat()
  on_delete_chat(chat_id)          — single delete from row context menu
  on_delete_many(ids: list[str])   — multi-delete
  on_rename_chat(chat_id, title)
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


# ── Single chat row ────────────────────────────────────────────────────────

class ChatRow(Gtk.ListBoxRow):
    def __init__(self, chat: Chat, on_delete, on_rename):
        super().__init__()
        self.chat_id = chat.id
        self._on_delete = on_delete
        self._on_rename = on_rename
        self._select_mode = False

        self._build(chat)

    def _build(self, chat: Chat):
        # Root box: [checkbox?] [texts] [⋮ button]
        self._root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._root.set_margin_top(6)
        self._root.set_margin_bottom(6)
        self._root.set_margin_start(12)
        self._root.set_margin_end(8)
        self.set_child(self._root)

        # Checkbox (hidden until select mode)
        self._check = Gtk.CheckButton()
        self._check.set_visible(False)
        self._check.set_valign(Gtk.Align.CENTER)
        self._root.append(self._check)

        # Text column
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        self._root.append(text_box)

        self._title_label = Gtk.Label(label=chat.title)
        self._title_label.set_xalign(0)
        self._title_label.set_ellipsize(3)
        self._title_label.set_max_width_chars(28)
        text_box.append(self._title_label)

        date_lbl = Gtk.Label(label=_format_date(chat.last_updated()))
        date_lbl.set_xalign(0)
        date_lbl.set_css_classes(["caption", "dim-label"])
        text_box.append(date_lbl)

        # Context menu button (hidden in select mode)
        self._menu_btn = Gtk.MenuButton()
        self._menu_btn.set_icon_name("view-more-symbolic")
        self._menu_btn.add_css_class("flat")
        self._menu_btn.set_valign(Gtk.Align.CENTER)
        self._root.append(self._menu_btn)

        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pop_box.set_margin_top(4)
        pop_box.set_margin_bottom(4)
        pop_box.set_margin_start(4)
        pop_box.set_margin_end(4)

        rename_btn = Gtk.Button(label="Rename")
        rename_btn.add_css_class("flat")
        rename_btn.connect("clicked", self._do_rename)
        pop_box.append(rename_btn)

        delete_btn = Gtk.Button(label="Delete")
        delete_btn.add_css_class("flat")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self._do_delete)
        pop_box.append(delete_btn)

        popover = Gtk.Popover()
        popover.set_child(pop_box)
        self._menu_btn.set_popover(popover)

    # ------------------------------------------------------------------ #
    # Select mode
    # ------------------------------------------------------------------ #

    def set_select_mode(self, active: bool):
        self._select_mode = active
        self._check.set_visible(active)
        self._menu_btn.set_visible(not active)
        if not active:
            self._check.set_active(False)

    def is_checked(self) -> bool:
        return self._check.get_active()

    def set_checked(self, val: bool):
        self._check.set_active(val)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def update_title(self, title: str):
        self._title_label.set_label(title)

    def _do_delete(self, _btn):
        self._menu_btn.get_popover().popdown()
        if self._on_delete:
            self._on_delete(self.chat_id)

    def _do_rename(self, _btn):
        self._menu_btn.get_popover().popdown()
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

    def _on_rename_response(self, _dialog, response, entry):
        if response == "rename":
            t = entry.get_text().strip()
            if t and self._on_rename:
                self._on_rename(self.chat_id, t)


# ── Sidebar ────────────────────────────────────────────────────────────────

class Sidebar(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Public callbacks
        self.on_chat_selected = None
        self.on_new_chat = None
        self.on_delete_chat = None
        self.on_delete_many = None
        self.on_rename_chat = None

        self._rows: dict[str, ChatRow] = {}
        self._select_mode = False

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Gtk.Label(label="Chats"))
        self.append(header)

        # Three-dot menu (left of header)
        self._header_menu_btn = Gtk.MenuButton()
        self._header_menu_btn.set_icon_name("view-more-symbolic")
        self._header_menu_btn.add_css_class("flat")
        header.pack_start(self._header_menu_btn)

        self._build_header_menu()

        # ── Search ────────────────────────────────────────────────
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search…")
        self._search_entry.set_margin_start(8)
        self._search_entry.set_margin_end(8)
        self._search_entry.set_margin_top(6)
        self._search_entry.set_margin_bottom(4)
        self._search_entry.connect("search-changed", self._on_search_changed)
        self.append(self._search_entry)

        # ── Chat list ─────────────────────────────────────────────
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

        # ── Multi-select action bar (hidden by default) ────────────
        self._action_bar = Gtk.ActionBar()
        self._action_bar.set_visible(False)

        self._del_sel_btn = Gtk.Button(label="Delete selected")
        self._del_sel_btn.add_css_class("destructive-action")
        self._del_sel_btn.connect("clicked", self._on_delete_selected)
        self._action_bar.pack_start(self._del_sel_btn)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self._set_select_mode(False))
        self._action_bar.pack_end(cancel_btn)

        self.append(self._action_bar)

        # ── New Chat button (bottom) ───────────────────────────────
        new_btn = Gtk.Button(label="+ New Chat")
        new_btn.add_css_class("suggested-action")
        new_btn.set_margin_start(8)
        new_btn.set_margin_end(8)
        new_btn.set_margin_top(6)
        new_btn.set_margin_bottom(8)
        new_btn.connect("clicked", lambda _: self.on_new_chat and self.on_new_chat())
        self._new_btn = new_btn
        self.append(new_btn)

    def _build_header_menu(self):
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pop_box.set_margin_top(4)
        pop_box.set_margin_bottom(4)
        pop_box.set_margin_start(4)
        pop_box.set_margin_end(4)

        self._select_btn = Gtk.Button(label="Select chats")
        self._select_btn.add_css_class("flat")
        self._select_btn.connect("clicked", self._on_toggle_select_mode)
        pop_box.append(self._select_btn)

        self._sel_all_btn = Gtk.Button(label="Select all")
        self._sel_all_btn.add_css_class("flat")
        self._sel_all_btn.set_sensitive(False)
        self._sel_all_btn.connect("clicked", self._on_select_all)
        pop_box.append(self._sel_all_btn)

        self._desel_all_btn = Gtk.Button(label="Deselect all")
        self._desel_all_btn.add_css_class("flat")
        self._desel_all_btn.set_sensitive(False)
        self._desel_all_btn.connect("clicked", self._on_deselect_all)
        pop_box.append(self._desel_all_btn)

        popover = Gtk.Popover()
        popover.set_child(pop_box)
        self._header_menu_btn.set_popover(popover)

    # ------------------------------------------------------------------ #
    # Select mode
    # ------------------------------------------------------------------ #

    def _set_select_mode(self, active: bool):
        self._select_mode = active
        self._action_bar.set_visible(active)
        self._new_btn.set_visible(not active)
        self._select_btn.set_label("Cancel selection" if active else "Select chats")
        self._sel_all_btn.set_sensitive(active)
        self._desel_all_btn.set_sensitive(active)
        # Disable normal row activation in select mode
        self._list_box.set_selection_mode(
            Gtk.SelectionMode.NONE if active else Gtk.SelectionMode.SINGLE
        )
        for row in self._rows.values():
            row.set_select_mode(active)
        # Close the popover
        self._header_menu_btn.get_popover().popdown()

    def _on_toggle_select_mode(self, _btn):
        self._set_select_mode(not self._select_mode)

    def _on_select_all(self, _btn):
        self._header_menu_btn.get_popover().popdown()
        for row in self._rows.values():
            row.set_checked(True)

    def _on_deselect_all(self, _btn):
        self._header_menu_btn.get_popover().popdown()
        for row in self._rows.values():
            row.set_checked(False)

    def _on_delete_selected(self, _btn):
        ids = [cid for cid, row in self._rows.items() if row.is_checked()]
        if not ids:
            return
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading=f"Delete {len(ids)} chat{'s' if len(ids) != 1 else ''}?",
            body="This action cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda d, r: self._confirm_delete_many(ids) if r == "delete" else None)
        dialog.present()

    def _confirm_delete_many(self, ids: list):
        self._set_select_mode(False)
        if self.on_delete_many:
            self.on_delete_many(ids)

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
        if self._select_mode:
            row.set_checked(not row.is_checked())
            return
        if self.on_chat_selected:
            self.on_chat_selected(row.chat_id)

    def _on_search_changed(self, entry):
        self._search_query = entry.get_text().lower()
        self._list_box.invalidate_filter()

    def _filter_func(self, row: ChatRow) -> bool:
        if not self._search_query:
            return True
        return self._search_query in row._title_label.get_label().lower()