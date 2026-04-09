from collections import Counter
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from datasets import Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

MODEL_NAME = "meta-llama/Llama-Prompt-Guard-2-86M"
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
HF_CACHE_DIR = DATA_DIR / "hf_cache"
OUTPUT_DIR = ROOT / "models" / "finetuned-prompt-guard"
TRAIN_FILE = DATA_DIR / "prompt_guard_train.jsonl"
MAX_LENGTH = 512
EPOCHS = 2


def _find_text_key(sample: dict[str, Any]) -> str:
    candidates = [
        "text",
        "prompt",
        "input",
        "question",
        "query",
        "instruction",
        "content",
        "goal",
    ]
    for key in candidates:
        if key in sample and isinstance(sample[key], str):
            return key

    for key, value in sample.items():
        if isinstance(value, str):
            return key

    raise ValueError("Could not determine text field in dataset row.")


def _find_label_key(sample: dict[str, Any]) -> str | None:
    candidates = [
        "label",
        "labels",
        "is_injection",
        "is_jailbreak",
        "target",
        "class",
        "attack",
    ]
    for key in candidates:
        if key in sample:
            return key
    return None


def _normalize_label(value: Any, text: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, np.integer, float)):
        return int(int(value) == 1)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "malicious", "injection", "jailbreak", "unsafe", "attack"}:
            return 1
        if v in {"0", "false", "no", "benign", "safe", "normal"}:
            return 0

    fallback_keywords = ["ignore", "system prompt", "developer mode", "override", "jailbreak", "leak"]
    return int(any(word in text.lower() for word in fallback_keywords))


def _load_training_split() -> Dataset:
    if not TRAIN_FILE.exists():
        raise FileNotFoundError(
            f"Missing {TRAIN_FILE}. Run src/training/prepare_datasets.py first."
        )
    return Dataset.from_json(str(TRAIN_FILE), cache_dir=str(HF_CACHE_DIR))


def _remove_eval_overlap(dataset: Dataset, text_key: str) -> Dataset:
    eval_file = DATA_DIR / "pyrit_test_prompts.jsonl"
    if not eval_file.exists():
        return dataset

    eval_set: set[str] = set()
    for line in eval_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        prompt = str(payload.get("prompt", "")).strip()
        if prompt:
            eval_set.add(prompt)

    if not eval_set:
        return dataset

    return dataset.filter(lambda row: str(row[text_key]).strip() not in eval_set)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=2,
        id2label={0: "SAFE", 1: "INJECTION"},
        label2id={"SAFE": 0, "INJECTION": 1},
    )

    train_ds = _load_training_split()

    sample = train_ds[0]
    text_key = _find_text_key(sample)
    label_key = _find_label_key(sample)

    train_ds = _remove_eval_overlap(train_ds, text_key)

    raw_texts = [str(item) for item in train_ds[text_key]]
    if label_key:
        raw_labels = train_ds[label_key]
    else:
        raw_labels = [None] * len(raw_texts)

    normalized_labels = [_normalize_label(label, text) for label, text in zip(raw_labels, raw_texts)]
    class_counts = Counter(normalized_labels)
    num_safe = class_counts.get(0, 0)
    num_injection = class_counts.get(1, 0)
    total_samples = num_safe + num_injection

    if total_samples == 0:
        raise ValueError("Dataset is empty or has no valid labels.")

    # Balanced class weight: total/(num_classes * class_count)
    w_safe = total_samples / (2 * max(num_safe, 1))
    w_injection = total_samples / (2 * max(num_injection, 1))
    class_weights = torch.tensor([w_safe, w_injection], dtype=torch.float32)

    def preprocess(batch: dict[str, Any]) -> dict[str, Any]:
        texts = [str(t) for t in batch[text_key]]
        if label_key:
            raw_labels = batch[label_key]
        else:
            raw_labels = [None] * len(texts)

        labels = [_normalize_label(label, text) for label, text in zip(raw_labels, texts)]
        tokenized = tokenizer(texts, truncation=True, max_length=MAX_LENGTH)
        tokenized["labels"] = labels
        return tokenized

    tokenized_train = train_ds.map(preprocess, batched=True, remove_columns=train_ds.column_names)

    eval_size = min(2000, max(500, len(tokenized_train) // 20))
    splits = tokenized_train.train_test_split(test_size=eval_size, seed=42) if len(tokenized_train) > (eval_size + 100) else {"train": tokenized_train, "test": None}

    use_fp16 = torch.cuda.is_available()
    training_args = TrainingArguments(
        output_dir=str(ROOT / "models" / "training-output"),
        num_train_epochs=EPOCHS,
        learning_rate=2e-5,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=16,
        gradient_accumulation_steps=2,
        fp16=use_fp16,
        evaluation_strategy="epoch" if splits["test"] is not None else "no",
        save_strategy="epoch",
        logging_steps=50,
        report_to="none",
        save_total_limit=2,
    )

    class WeightedTrainer(Trainer):
        def __init__(self, class_weights_tensor: torch.Tensor, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self.class_weights = class_weights_tensor

        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels = inputs["labels"].long()
            model_inputs = {k: v for k, v in inputs.items() if k != "labels"}
            outputs = model(**model_inputs)
            logits = outputs.logits
            loss_fct = torch.nn.CrossEntropyLoss(weight=self.class_weights.to(logits.device))
            loss = loss_fct(logits, labels)
            return (loss, outputs) if return_outputs else loss

    trainer = WeightedTrainer(
        class_weights_tensor=class_weights,
        model=model,
        args=training_args,
        train_dataset=splits["train"],
        eval_dataset=splits["test"],
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        tokenizer=tokenizer,
    )

    trainer.train()
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print(f"Training file source: {TRAIN_FILE}")
    print(f"Train label distribution -> SAFE(0): {num_safe}, INJECTION(1): {num_injection}")
    print(f"Class weights -> SAFE(0): {w_safe:.4f}, INJECTION(1): {w_injection:.4f}")
    print(f"Train samples used: {len(splits['train'])}")
    if splits["test"] is not None:
        print(f"Eval samples used: {len(splits['test'])}")
    print(f"Mixed precision fp16 enabled: {use_fp16}")
    print(f"Saved fine-tuned model to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
