"""
Streaming inference engine.

InferenceEngine.generate_async(messages, on_token, on_done, on_error)
  - messages: list of {"role": ..., "content": ...} dicts (including system)
  - on_token(text): called on the GTK main thread with each new text chunk
  - on_done():      called when generation finishes normally
  - on_error(msg):  called if an exception occurs

Generation runs in a daemon thread. Call stop() to request early termination.
"""

import threading
from typing import Callable, List, Dict, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from transformers import TextIteratorStreamer


class InferenceEngine:
    """
    Wraps a loaded HuggingFace model and tokenizer for streaming generation.
    Thread-safe: only one generation may run at a time.
    """

    def __init__(self, model, tokenizer):
        self._model = model
        self._tokenizer = tokenizer
        self._stop_event = threading.Event()
        self._running = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate_async(
        self,
        messages: List[Dict[str, str]],
        on_token: Callable[[str], None],
        on_done: Callable[[], None],
        on_error: Callable[[str], None],
        max_new_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ):
        """Kick off a streamed generation in a background thread."""
        if self._running:
            return  # ignore concurrent requests

        self._stop_event.clear()
        t = threading.Thread(
            target=self._generate_worker,
            args=(messages, on_token, on_done, on_error, max_new_tokens, temperature, top_p),
            daemon=True,
        )
        t.start()

    def stop(self):
        """Request that the current generation stops after the next token."""
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Worker
    # ------------------------------------------------------------------ #

    def _generate_worker(
        self,
        messages,
        on_token,
        on_done,
        on_error,
        max_new_tokens,
        temperature,
        top_p,
    ):
        self._running = True
        try:
            import torch

            tok = self._tokenizer
            model = self._model

            # Apply chat template — returns a BatchEncoding (dict-like), not a raw tensor
            encoded = tok.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            )
            # Move all tensors to the model's device
            encoded = {k: v.to(model.device) for k, v in encoded.items()}

            # TextIteratorStreamer yields decoded text chunks in real time
            streamer = TextIteratorStreamer(
                tok,
                skip_prompt=True,
                skip_special_tokens=True,
            )

            gen_kwargs = dict(
                **encoded,
                streamer=streamer,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=temperature > 0,
            )

            # model.generate() must run in a thread; the streamer bridges it
            gen_thread = threading.Thread(
                target=model.generate, kwargs=gen_kwargs, daemon=True
            )
            gen_thread.start()

            for text in streamer:
                if self._stop_event.is_set():
                    break
                if text:
                    # Schedule on GTK main thread
                    GLib.idle_add(on_token, text)

            gen_thread.join(timeout=0)  # don't block; it may still be running
            GLib.idle_add(on_done)

        except Exception as e:
            GLib.idle_add(on_error, str(e))
        finally:
            self._running = False

    @property
    def is_running(self) -> bool:
        return self._running