import json
from pathlib import Path
from typing import Any

from datasets import Dataset, DatasetDict, load_dataset

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
HF_CACHE_DIR = DATA_DIR / "hf_cache"

PYRIT_PROMPTS_FILE = DATA_DIR / "pyrit_test_prompts.jsonl"
TRAIN_FILE = DATA_DIR / "prompt_guard_train.jsonl"
MANIFEST_FILE = DATA_DIR / "dataset_manifest.json"

MIN_PYRIT_SAMPLES = 1000


def _to_rows(ds: Dataset) -> list[dict[str, Any]]:
    return [ds[i] for i in range(len(ds))]


def _is_malicious_row(row: dict[str, Any]) -> bool:
    malicious_keywords = {
        "1",
        "true",
        "yes",
        "malicious",
        "injection",
        "jailbreak",
        "unsafe",
        "attack",
    }
    safe_keywords = {"0", "false", "no", "benign", "safe", "normal"}

    for key, value in row.items():
        key_lower = key.lower()
        if any(term in key_lower for term in ("label", "class", "attack", "jailbreak", "injection", "target")):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return int(value) == 1
            if isinstance(value, str):
                low = value.strip().lower()
                if low in malicious_keywords:
                    return True
                if low in safe_keywords:
                    return False

    return True


def _extract_text_field(row: dict[str, Any]) -> str | None:
    text_candidates = [
        "prompt",
        "text",
        "input",
        "query",
        "question",
        "instruction",
        "content",
        "goal",
        "jailbreak_prompt",
    ]

    for key in text_candidates:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for value in row.values():
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _normalize_label(value: Any, text: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(int(value) == 1)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "malicious", "injection", "jailbreak", "unsafe", "attack"}:
            return 1
        if v in {"0", "false", "no", "benign", "safe", "normal"}:
            return 0

    fallback_keywords = ["ignore", "system prompt", "developer mode", "override", "jailbreak", "leak"]
    return int(any(word in text.lower() for word in fallback_keywords))


def _load_pyrit_eval_sources() -> list[tuple[list[dict[str, Any]], str, str]]:
    sources: list[tuple[list[dict[str, Any]], str, str]] = []

    try:
        jbb = load_dataset("JailbreakBench/JBB-Behaviors", "behaviors", cache_dir=str(HF_CACHE_DIR))
        if isinstance(jbb, DatasetDict):
            split_name = "test" if "test" in jbb else next(iter(jbb.keys()))
            sources.append((_to_rows(jbb[split_name]), "JailbreakBench/JBB-Behaviors", split_name))
        else:
            sources.append((_to_rows(jbb), "JailbreakBench/JBB-Behaviors", "default"))
    except Exception:
        pass

    try:
        pid = load_dataset("neuralchemy/Prompt-injection-dataset", "core", cache_dir=str(HF_CACHE_DIR))
        if not isinstance(pid, DatasetDict):
            pid = DatasetDict({"test": pid})
        for split_name in ["test", "validation"]:
            if split_name in pid:
                sources.append((_to_rows(pid[split_name]), "neuralchemy/Prompt-injection-dataset", split_name))
        if not any(name == "neuralchemy/Prompt-injection-dataset" for _, name, _ in sources):
            fallback_split = next(iter(pid.keys()))
            sources.append((_to_rows(pid[fallback_split]), "neuralchemy/Prompt-injection-dataset", fallback_split))
    except Exception:
        pass

    if not sources:
        raise RuntimeError("Could not load any independent evaluation dataset source.")

    return sources


def _load_train_rows() -> tuple[list[dict[str, Any]], str, str]:
    try:
        train_ds = load_dataset(
            "neuralchemy/Prompt-injection-dataset",
            "full",
            split="train",
            cache_dir=str(HF_CACHE_DIR),
        )
        return _to_rows(train_ds), "neuralchemy/Prompt-injection-dataset/full", "train"
    except Exception:
        fallback = load_dataset("Mindgard/evaded-prompt-injection-and-jailbreak-samples", cache_dir=str(HF_CACHE_DIR))
        if isinstance(fallback, DatasetDict):
            split_name = "train" if "train" in fallback else next(iter(fallback.keys()))
            return _to_rows(fallback[split_name]), "Mindgard/evaded-prompt-injection-and-jailbreak-samples", split_name
        return _to_rows(fallback), "Mindgard/evaded-prompt-injection-and-jailbreak-samples", "default"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    eval_sources = _load_pyrit_eval_sources()
    pyrit_prompts: list[dict[str, Any]] = []
    pyrit_seen: set[str] = set()
    eval_source_meta: list[dict[str, str | int]] = []

    for eval_rows, eval_dataset, eval_split in eval_sources:
        before = len(pyrit_prompts)
        for row in eval_rows:
            if not _is_malicious_row(row):
                continue
            prompt = _extract_text_field(row)
            if not prompt or prompt in pyrit_seen:
                continue
            pyrit_seen.add(prompt)
            pyrit_prompts.append({"prompt": prompt})
            if len(pyrit_prompts) >= MIN_PYRIT_SAMPLES:
                break

        eval_source_meta.append(
            {
                "dataset": eval_dataset,
                "split": eval_split,
                "contributed": len(pyrit_prompts) - before,
            }
        )

        if len(pyrit_prompts) >= MIN_PYRIT_SAMPLES:
            break

    if len(pyrit_prompts) < MIN_PYRIT_SAMPLES:
        raise RuntimeError(
            f"Only collected {len(pyrit_prompts)} eval prompts. Need at least {MIN_PYRIT_SAMPLES}."
        )

    train_rows, train_dataset, train_split = _load_train_rows()
    train_records: list[dict[str, Any]] = []
    eval_prompt_set = {item["prompt"] for item in pyrit_prompts}

    for row in train_rows:
        text = _extract_text_field(row)
        if not text:
            continue

        if text in eval_prompt_set:
            continue

        label_value = None
        for k in ("label", "labels", "is_injection", "is_jailbreak", "target", "class", "attack"):
            if k in row:
                label_value = row[k]
                break

        label = _normalize_label(label_value, text)
        train_records.append({"text": text, "label": label})

    if not train_records:
        raise RuntimeError("No training records were prepared.")

    _write_jsonl(PYRIT_PROMPTS_FILE, pyrit_prompts)
    _write_jsonl(TRAIN_FILE, train_records)

    manifest = {
        "pyrit_eval": {
            "sources": eval_source_meta,
            "samples": len(pyrit_prompts),
            "file": str(PYRIT_PROMPTS_FILE),
        },
        "prompt_guard_train": {
            "dataset": train_dataset,
            "split": train_split,
            "samples": len(train_records),
            "file": str(TRAIN_FILE),
            "overlap_removed_against": str(PYRIT_PROMPTS_FILE),
        },
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    print(f"Saved PyRIT test set: {PYRIT_PROMPTS_FILE} ({len(pyrit_prompts)} prompts)")
    print(f"Saved Prompt-Guard train set: {TRAIN_FILE} ({len(train_records)} records)")
    print(f"Saved manifest: {MANIFEST_FILE}")


if __name__ == "__main__":
    main()
