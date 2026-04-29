"""
MainWindow — the top-level application window.

Wires together:
  - Sidebar (chat list)
  - ChatView (message area)
  - ModelManager (load/download models)
  - InferenceEngine (streaming generation)
  - ChatStore (persistence)
  - Settings (user preferences)

Uses AdwNavigationSplitView for the sidebar/content split so the layout
automatically collapses to a single-panel view on narrow screens.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from app.sidebar import Sidebar
from app.chat_view import ChatView
from app.model_manager import ModelManager, ModelInfo
from app.inference import InferenceEngine
from app.chat_store import Chat, ChatStore, Message
from app.settings import settings


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._chat: Chat | None = None
        self._engine: InferenceEngine | None = None
        self._model_mgr = ModelManager()

        self.set_title("Local AI Chat")
        self.set_default_size(
            settings.get("window_width"),
            settings.get("window_height"),
        )

        self._build_ui()
        self._connect_model_manager()

        # Load last-used model on startup if set
        last = settings.last_model
        if last and self._model_mgr.is_model_cached(last):
            self._model_mgr.load_model_async(last)
        elif self._model_mgr.get_available_models():
            # Pre-select first model in dropdown without loading
            self._model_dropdown.set_selected(0)

        # Open most recent chat or create a new one
        chats = ChatStore.list_chats()
        if chats:
            self._open_chat(chats[0].id)
        else:
            self._create_new_chat()

    # ──────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Root overlay layout
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # ── Top headerbar ────────────────────────────────────────────
        self._headerbar = Adw.HeaderBar()
        self._title_label = Gtk.Label(label="New Chat")
        self._title_label.add_css_class("heading")
        self._headerbar.set_title_widget(self._title_label)
        toolbar_view.add_top_bar(self._headerbar)

        # Model dropdown in headerbar
        models = self._model_mgr.get_available_models()
        model_names = [m.name for m in models]
        self._model_list = Gtk.StringList.new(model_names)
        self._model_dropdown = Gtk.DropDown(model=self._model_list)
        self._model_dropdown.set_tooltip_text("Select model")
        self._model_dropdown.connect("notify::selected", self._on_model_selected)
        self._headerbar.pack_end(self._model_dropdown)

        # Settings button
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("Menu")
        menu_btn.set_popover(self._build_settings_popover())
        self._headerbar.pack_end(menu_btn)

        # ── Navigation split view (sidebar + content) ────────────────
        self._split_view = Adw.NavigationSplitView()
        toolbar_view.set_content(self._split_view)

        # Sidebar navigation page
        self._sidebar = Sidebar()
        self._sidebar.set_size_request(260, -1)
        self._sidebar.on_chat_selected = self._open_chat
        self._sidebar.on_new_chat = self._create_new_chat
        self._sidebar.on_delete_chat = self._confirm_delete_chat
        self._sidebar.on_rename_chat = self._do_rename_chat

        sidebar_page = Adw.NavigationPage(title="Chats")
        sidebar_page.set_child(self._sidebar)
        self._split_view.set_sidebar(sidebar_page)

        # Chat view navigation page
        self._chat_view = ChatView()
        self._chat_view.set_callbacks(
            on_send=self._on_user_send,
            on_stop=self._on_stop_generation,
        )

        content_page = Adw.NavigationPage(title="Chat")
        content_page.set_child(self._chat_view)
        self._split_view.set_content(content_page)

        # Status bar (loading indicator)
        self._status_bar = Gtk.Label(label="")
        self._status_bar.set_margin_start(8)
        self._status_bar.add_css_class("dim-label")
        self._status_bar.add_css_class("caption")
        toolbar_view.add_bottom_bar(self._status_bar)

    def _build_settings_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        pop.set_child(box)

        # Default system prompt
        box.append(Gtk.Label(label="Default system prompt", xalign=0))
        self._default_sp_entry = Gtk.Entry()
        self._default_sp_entry.set_text(settings.default_system_prompt)
        self._default_sp_entry.set_size_request(280, -1)
        box.append(self._default_sp_entry)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_default_sp)
        box.append(save_btn)

        return pop

    # ──────────────────────────────────────────────────────────────────
    # Model manager callbacks
    # ──────────────────────────────────────────────────────────────────

    def _connect_model_manager(self):
        m = self._model_mgr
        m.on_load_started = self._on_model_load_started
        m.on_load_done = self._on_model_load_done
        m.on_load_error = self._on_model_load_error
        m.on_download_done = self._on_download_done
        m.on_download_error = self._on_download_error

    def _on_model_load_started(self):
        self._set_status("Loading model…")
        self._chat_view.set_input_sensitive(False)

    def _on_model_load_done(self, model, tokenizer):
        self._engine = InferenceEngine(model, tokenizer)
        self._set_status(f"Model ready: {self._model_mgr.current_hf_id}")
        self._chat_view.set_input_sensitive(True)
        settings.last_model = self._model_mgr.current_hf_id

    def _on_model_load_error(self, msg: str):
        self._set_status(f"Model error: {msg}")
        self._chat_view.set_input_sensitive(False)
        self._show_error_dialog("Model load failed", msg)

    def _on_download_done(self):
        self._set_status("Download complete. Loading model…")
        # Now load it
        idx = self._model_dropdown.get_selected()
        models = self._model_mgr.get_available_models()
        if 0 <= idx < len(models):
            self._model_mgr.load_model_async(models[idx].hf_id)

    def _on_download_error(self, msg: str):
        self._set_status(f"Download failed: {msg}")
        self._show_error_dialog("Download failed", msg)

    # ──────────────────────────────────────────────────────────────────
    # Model dropdown
    # ──────────────────────────────────────────────────────────────────

    def _on_model_selected(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        models = self._model_mgr.get_available_models()
        if not (0 <= idx < len(models)):
            return
        info: ModelInfo = models[idx]

        if self._model_mgr.is_model_cached(info.hf_id):
            self._model_mgr.load_model_async(info.hf_id)
        else:
            self._show_download_dialog(info)

    def _show_download_dialog(self, info: ModelInfo):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Download {info.name}?",
            body=f"{info.description}\n\nThis model is not downloaded yet. "
                 f"Download it now?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("download", "Download")
        dialog.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_download_response, info)
        dialog.present()

    def _on_download_response(self, dialog, response: str, info: ModelInfo):
        if response == "download":
            self._set_status(f"Downloading {info.name}…")
            self._model_mgr.download_model_async(info.hf_id)

    # ──────────────────────────────────────────────────────────────────
    # Chat management
    # ──────────────────────────────────────────────────────────────────

    def _create_new_chat(self):
        chat = ChatStore.new_chat(
            system_prompt=settings.default_system_prompt,
            model=self._model_mgr.current_hf_id,
        )
        ChatStore.save_chat(chat)
        self._sidebar.prepend_chat(chat)
        self._load_chat_into_view(chat)

    def _open_chat(self, chat_id: str):
        chat = ChatStore.load_chat(chat_id)
        if chat is None:
            return
        self._sidebar.select_chat(chat_id)
        self._load_chat_into_view(chat)

    def _load_chat_into_view(self, chat: Chat):
        self._chat = chat
        self._title_label.set_label(chat.title)
        self._chat_view.load_chat(chat)

    def _confirm_delete_chat(self, chat_id: str):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Delete chat?",
            body="This action cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda d, r: self._do_delete_chat(chat_id) if r == "delete" else None)
        dialog.present()

    def _do_rename_chat(self, chat_id: str, new_title: str):
        chat = ChatStore.load_chat(chat_id)
        if chat:
            chat.title = new_title
            ChatStore.save_chat(chat)
            self._sidebar.update_chat_title(chat_id, new_title)
            if self._chat and self._chat.id == chat_id:
                self._chat.title = new_title
                self._title_label.set_label(new_title)

    def _do_delete_chat(self, chat_id: str):
        ChatStore.delete_chat(chat_id)
        self._sidebar.remove_chat(chat_id)
        if self._chat and self._chat.id == chat_id:
            self._chat = None
            chats = ChatStore.list_chats()
            if chats:
                self._open_chat(chats[0].id)
            else:
                self._create_new_chat()

    # ──────────────────────────────────────────────────────────────────
    # Sending messages / generation
    # ──────────────────────────────────────────────────────────────────

    def _on_user_send(self, text: str):
        if self._engine is None:
            self._show_error_dialog("No model loaded", "Please select a model from the dropdown first.")
            return
        if not self._chat:
            return

        # Add user message to chat and display it
        user_msg = Message(role="user", content=text)
        self._chat.messages.append(user_msg)

        # Auto-title from first message
        if len(self._chat.messages) == 1:
            self._chat.title = self._chat.auto_title()
            self._title_label.set_label(self._chat.title)
            self._sidebar.update_chat_title(self._chat.id, self._chat.title)

        ChatStore.save_chat(self._chat)
        self._chat_view.append_user_message(text)
        self._chat_view.set_input_sensitive(False)
        self._chat_view.begin_streaming()

        # Build messages list for the model (with system prompt)
        msgs = [{"role": "system", "content": self._chat.system_prompt}]
        for m in self._chat.messages:
            msgs.append({"role": m.role, "content": m.content})

        self._engine.generate_async(
            messages=msgs,
            on_token=self._on_token,
            on_done=self._on_generation_done,
            on_error=self._on_generation_error,
        )

    def _on_token(self, token: str):
        self._chat_view.append_token(token)

    def _on_generation_done(self):
        full_text = self._chat_view.finish_streaming()
        if self._chat and full_text:
            asst_msg = Message(role="assistant", content=full_text)
            self._chat.messages.append(asst_msg)
            ChatStore.save_chat(self._chat)
        self._chat_view.set_input_sensitive(True)

    def _on_generation_error(self, msg: str):
        self._chat_view.finish_streaming()
        self._chat_view.set_input_sensitive(True)
        self._show_error_dialog("Generation error", msg)

    def _on_stop_generation(self):
        if self._engine:
            self._engine.stop()

    # ──────────────────────────────────────────────────────────────────
    # Settings
    # ──────────────────────────────────────────────────────────────────

    def _on_save_default_sp(self, _btn):
        sp = self._default_sp_entry.get_text().strip()
        if sp:
            settings.default_system_prompt = sp

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_bar.set_label(msg)

    def _show_error_dialog(self, title: str, body: str):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=title,
            body=body,
        )
        dialog.add_response("ok", "OK")
        dialog.present()