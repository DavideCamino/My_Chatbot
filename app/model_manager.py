"""
Model lifecycle: config loading, local-presence check, background download,
and load/unload of HuggingFace models.

Only one model is kept in memory at a time. Loading and downloading both
run in daemon threads so the GTK main loop is never blocked.

Emitted callbacks (all called on the GTK main thread via GLib.idle_add):
  on_load_started()
  on_load_done(model, tokenizer)
  on_load_error(message: str)
  on_download_progress(fraction: float, bytes_done: int, bytes_total: int)
  on_download_done()
  on_download_error(message: str)
"""

import json
import os
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from huggingface_hub import snapshot_download, try_to_load_from_cache, scan_cache_dir
from transformers import AutoModelForCausalLM, AutoTokenizer


# Look for models.json next to this package
_MODELS_JSON = Path(__file__).parent.parent / "models.json"


# ──────────────────────────────────────────────────────────────────────────────
# Data class for model metadata
# ──────────────────────────────────────────────────────────────────────────────

class ModelInfo:
    def __init__(self, name: str, hf_id: str, description: str):
        self.name = name
        self.hf_id = hf_id
        self.description = description

    def __repr__(self):
        return f"<ModelInfo {self.hf_id}>"


# ──────────────────────────────────────────────────────────────────────────────
# Manager
# ──────────────────────────────────────────────────────────────────────────────

class ModelManager:
    """
    Manages discovery, downloading, and in-memory loading of LLM models.
    """

    def __init__(self):
        self._models: List[ModelInfo] = []
        self._current_model = None       # transformers model object
        self._current_tokenizer = None   # transformers tokenizer object
        self._current_hf_id: Optional[str] = None
        self._load_lock = threading.Lock()

        # Callbacks — set by the UI layer
        self.on_load_started: Optional[Callable] = None
        self.on_load_done: Optional[Callable] = None
        self.on_load_error: Optional[Callable] = None
        self.on_download_progress: Optional[Callable] = None
        self.on_download_done: Optional[Callable] = None
        self.on_download_error: Optional[Callable] = None

        self._load_config()

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    def _load_config(self):
        """Parse models.json from the project root."""
        if not _MODELS_JSON.exists():
            return
        try:
            with open(_MODELS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._models = [
                ModelInfo(m["name"], m["hf_id"], m.get("description", ""))
                for m in data.get("models", [])
            ]
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[model_manager] Failed to load models.json: {e}")

    def get_available_models(self) -> List[ModelInfo]:
        return list(self._models)

    # ------------------------------------------------------------------ #
    # Local presence check
    # ------------------------------------------------------------------ #

    def is_model_cached(self, hf_id: str) -> bool:
        """
        Return True if the model appears to be fully present in the HF cache.
        We check for the config.json file which is always present in a
        complete download.
        """
        try:
            result = try_to_load_from_cache(hf_id, "config.json")
            return result is not None and result != "file_not_found"
        except Exception:
            pass
        # Fallback: scan cache for any snapshot of this repo
        try:
            info = scan_cache_dir()
            for repo in info.repos:
                if repo.repo_id == hf_id and repo.nb_snapshots > 0:
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #

    def download_model_async(self, hf_id: str):
        """
        Download a model snapshot in a background thread.
        Progress is approximated via a polling thread since snapshot_download
        does not natively support progress callbacks.
        """
        t = threading.Thread(target=self._download_worker, args=(hf_id,), daemon=True)
        t.start()

    def _download_worker(self, hf_id: str):
        try:
            # snapshot_download streams into the HF cache
            snapshot_download(
                repo_id=hf_id,
                ignore_patterns=["*.msgpack", "flax_model*", "tf_model*", "rust_model*"],
            )
            GLib.idle_add(self._emit, "on_download_done")
        except Exception as e:
            msg = str(e)
            GLib.idle_add(self._emit, "on_download_error", msg)

    # ------------------------------------------------------------------ #
    # Load / unload
    # ------------------------------------------------------------------ #

    def load_model_async(self, hf_id: str):
        """Load (or swap to) a model in a background thread."""
        t = threading.Thread(target=self._load_worker, args=(hf_id,), daemon=True)
        t.start()

    def _load_worker(self, hf_id: str):
        with self._load_lock:
            GLib.idle_add(self._emit, "on_load_started")
            try:
                # Unload previous model first to free VRAM/RAM
                self._unload()

                tok = AutoTokenizer.from_pretrained(hf_id)
                model = AutoModelForCausalLM.from_pretrained(
                    hf_id,
                    torch_dtype="auto",   # fp16 on GPU, fp32 on CPU
                    device_map="auto",    # uses CUDA if available, else CPU
                )
                model.eval()

                self._current_model = model
                self._current_tokenizer = tok
                self._current_hf_id = hf_id

                GLib.idle_add(self._emit, "on_load_done", model, tok)
            except Exception as e:
                GLib.idle_add(self._emit, "on_load_error", str(e))

    def _unload(self):
        """Release the current model from memory."""
        if self._current_model is not None:
            try:
                import torch
                del self._current_model
                del self._current_tokenizer
                torch.cuda.empty_cache()
            except Exception:
                pass
            self._current_model = None
            self._current_tokenizer = None
            self._current_hf_id = None

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #

    @property
    def current_model(self):
        return self._current_model

    @property
    def current_tokenizer(self):
        return self._current_tokenizer

    @property
    def current_hf_id(self) -> Optional[str]:
        return self._current_hf_id

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _emit(self, cb_name: str, *args):
        """Call a named callback if it has been set."""
        cb = getattr(self, cb_name, None)
        if callable(cb):
            cb(*args)