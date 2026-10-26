# -*- coding: utf-8 -*-
"""本地分镜文案：Qwen2.5-1.5B-Instruct，纯 CPU 推理。"""

import os
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(ROOT, "models", "qwen-1.5b")

_lock = threading.Lock()
_model = None
_tokenizer = None


def is_ready() -> bool:
    return os.path.isdir(MODEL_DIR) and any(
        f.endswith(".safetensors") for f in os.listdir(MODEL_DIR))


def _load():
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(max(2, (os.cpu_count() or 4)))
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    try:  # transformers 5.x 用 dtype，旧版用 torch_dtype
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR, dtype=torch.float32, local_files_only=True)
    except TypeError:
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR, torch_dtype=torch.float32, local_files_only=True)
    _model.eval()
    return _model, _tokenizer


def chat(prompt: str, max_new_tokens: int = 1200) -> str:
    """单轮对话，返回模型回答文本。"""
    import torch

    with _lock:
        model, tok = _load()
        messages = [{"role": "user", "content": prompt}]
        text = tok.apply_chat_template(messages, tokenize=False,
                                       add_generation_prompt=True)
        inputs = tok(text, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=True,
                temperature=0.7, top_p=0.9, repetition_penalty=1.05,
                pad_token_id=tok.eos_token_id,
            )
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        return tok.decode(new_tokens, skip_special_tokens=True)
