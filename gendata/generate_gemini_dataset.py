import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def hash_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def infer_label_from_meta_prompt_path(meta_prompt_file: Path) -> Optional[int]:
    name = meta_prompt_file.name.lower()
    match = re.match(r"label([012])metaprompt\.md$", name)
    if not match:
        return None
    return int(match.group(1))


def extract_first_json_array(text: str) -> List[dict]:
    text = text.strip()
    # Gemini may sometimes wrap output in markdown fences, strip those first.
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, list):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("No valid JSON array found in Gemini response.")


def load_meta_prompt(meta_prompt_file: Path) -> str:
    if not meta_prompt_file.exists():
        raise FileNotFoundError(f"Meta prompt file not found: {meta_prompt_file}")
    return meta_prompt_file.read_text(encoding="utf-8").strip()


def load_existing_hashes_and_count(output_file: Path) -> Tuple[Set[str], int]:
    hashes: Set[str] = set()
    count = 0
    if not output_file.exists():
        return hashes, count

    with output_file.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                text = row.get("text")
                if isinstance(text, str) and text.strip():
                    hashes.add(hash_text(text))
                    count += 1
            except json.JSONDecodeError:
                print(
                    f"[WARN] Skip malformed JSONL line {line_number} in {output_file}",
                    file=sys.stderr,
                )
    return hashes, count


def build_prompt(meta_prompt: str, examples_per_call: int) -> str:
    # Keep the original meta prompt and enforce output size with a suffix instruction.
    return (
        f"{meta_prompt}\n\n"
        f"IMPORTANT: Return exactly {examples_per_call} objects in the JSON array."
    )


def call_gemini(
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    timeout_sec: int,
) -> str:
    url = GEMINI_API_BASE.format(model=urllib.parse.quote(model))
    url = f"{url}?key={urllib.parse.quote(api_key)}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }
    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(request, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8")

    response_obj = json.loads(raw)
    candidates = response_obj.get("candidates", [])
    if not candidates:
        raise ValueError(f"Gemini returned no candidates: {raw[:400]}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    output_text = "".join(text_parts).strip()
    if not output_text:
        raise ValueError(f"Gemini output text is empty: {raw[:400]}")
    return output_text


def classify_http_error(e: urllib.error.HTTPError) -> str:
    code = e.code
    if code == 429:
        return "rate_limit"
    if code in (500, 502, 503, 504):
        return "server_error"
    if code in (401, 403):
        return "auth_or_quota"
    return "other"


def sanitize_examples(examples: List[dict], forced_label: Optional[int] = None) -> List[Dict[str, object]]:
    cleaned: List[Dict[str, object]] = []
    for item in examples:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        label = forced_label if forced_label is not None else item.get("label")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue

        if isinstance(label, bool):
            continue
        if isinstance(label, str) and label.isdigit():
            label = int(label)
        if not isinstance(label, int) or label not in (0, 1, 2):
            continue
        cleaned.append({"text": text, "label": label})
    return cleaned


def append_jsonl_rows(output_file: Path, rows: List[Dict[str, object]]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate dataset with Gemini using a meta prompt and append to JSONL."
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("GEMINI_API_KEY", ""),
        help="Gemini API key. Defaults to GEMINI_API_KEY environment variable.",
    )
    parser.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name.")
    parser.add_argument(
        "--meta-prompt-file",
        default="gendata/metaprompt.md",
        help="Path to meta prompt file.",
    )
    parser.add_argument(
        "--output-file",
        default="gendata/generated_prompt_guard_5000.jsonl",
        help="Output JSONL file. New data will be appended.",
    )
    parser.add_argument(
        "--target-size",
        type=int,
        default=5000,
        help="Target number of rows in output file.",
    )
    parser.add_argument(
        "--examples-per-call",
        type=int,
        default=20,
        help="How many examples to request from Gemini each call.",
    )
    parser.add_argument(
        "--rpm",
        type=float,
        default=8.0,
        help="Max requests per minute to keep under rate limits.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help="Gemini temperature.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=90,
        help="HTTP timeout for each request in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=8,
        help="Max retries for one API call on recoverable errors.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="Random seed for jitter and retry randomness.",
    )
    parser.add_argument(
        "--manual-one-call",
        action="store_true",
        help="Manual mode: execute only one successful API call then exit.",
    )
    parser.add_argument(
        "--confirm-before-call",
        action="store_true",
        help="Ask for Enter confirmation before each API call.",
    )
    parser.add_argument(
        "--force-label",
        type=int,
        choices=[0, 1, 2],
        default=None,
        help="Force all generated rows to this label. If omitted, script auto-detects from meta prompt filename label0/1/2.",
    )
    args = parser.parse_args()

    if not args.api_key:
        print(
            "[ERROR] Missing API key. Provide --api-key or set GEMINI_API_KEY.",
            file=sys.stderr,
        )
        return 1
    if args.target_size <= 0:
        print("[ERROR] --target-size must be > 0", file=sys.stderr)
        return 1
    if args.examples_per_call <= 0:
        print("[ERROR] --examples-per-call must be > 0", file=sys.stderr)
        return 1
    if args.rpm <= 0:
        print("[ERROR] --rpm must be > 0", file=sys.stderr)
        return 1
    random.seed(args.seed)

    meta_prompt_file = Path(args.meta_prompt_file)
    output_file = Path(args.output_file)
    inferred_label = infer_label_from_meta_prompt_path(meta_prompt_file)
    effective_label = args.force_label if args.force_label is not None else inferred_label

    if effective_label is not None:
        print(f"[INFO] Effective label mode: force label={effective_label}")
    else:
        print("[INFO] Effective label mode: use labels returned by model")

    meta_prompt = load_meta_prompt(meta_prompt_file)
    prompt = build_prompt(meta_prompt, args.examples_per_call)

    known_hashes, existing_count = load_existing_hashes_and_count(output_file)
    print(f"[INFO] Output file: {output_file}")
    print(f"[INFO] Existing valid rows: {existing_count}")

    if existing_count >= args.target_size:
        print("[INFO] Target already reached. Nothing to do.")
        return 0

    min_interval_sec = 60.0 / args.rpm
    request_count = 0
    total_added = 0
    started_at = time.time()
    next_allowed_time = time.time()
    successful_calls = 0

    while existing_count + total_added < args.target_size:
        if args.confirm_before_call:
            input("[MANUAL] Press Enter to trigger next Gemini API call...")

        # Base throttle to avoid bursts that trigger account-level limits.
        sleep_needed = max(0.0, next_allowed_time - time.time())
        if sleep_needed > 0:
            time.sleep(sleep_needed)

        response_text: Optional[str] = None
        for attempt in range(args.max_retries + 1):
            try:
                response_text = call_gemini(
                    api_key=args.api_key,
                    model=args.model,
                    prompt=prompt,
                    temperature=args.temperature,
                    timeout_sec=args.timeout_sec,
                )
                break
            except urllib.error.HTTPError as e:
                kind = classify_http_error(e)
                payload = e.read().decode("utf-8", errors="replace")
                if attempt >= args.max_retries or kind == "other":
                    if e.code == 404:
                        print(
                            "[HINT] Model not found on v1beta generateContent. Try --model gemini-2.5-pro or --model gemini-2.5-flash.",
                            file=sys.stderr,
                        )
                    print(
                        f"[ERROR] HTTP {e.code} after retries exhausted. Body: {payload[:600]}",
                        file=sys.stderr,
                    )
                    return 2

                # Stronger cooldown for quota/rate errors to protect account limits.
                base_wait = min(180.0, (2 ** attempt) * 2.0)
                if kind in ("rate_limit", "auth_or_quota"):
                    base_wait = max(base_wait, 30.0)
                wait = base_wait + random.uniform(0.0, 2.5)
                print(
                    f"[WARN] HTTP {e.code} ({kind}), retry {attempt + 1}/{args.max_retries} in {wait:.1f}s"
                )
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
                if attempt >= args.max_retries:
                    print(f"[ERROR] Request/parse failed after retries: {e}", file=sys.stderr)
                    return 3
                wait = min(60.0, (2 ** attempt) * 1.5) + random.uniform(0.0, 1.5)
                print(
                    f"[WARN] Request/parse issue ({type(e).__name__}), retry {attempt + 1}/{args.max_retries} in {wait:.1f}s"
                )
                time.sleep(wait)

        if response_text is None:
            print("[ERROR] No response text after retry loop.", file=sys.stderr)
            return 4

        request_count += 1
        successful_calls += 1
        next_allowed_time = time.time() + min_interval_sec + random.uniform(0.05, 0.9)

        try:
            parsed = extract_first_json_array(response_text)
        except ValueError as e:
            print(f"[WARN] Skip one batch due to invalid JSON array: {e}")
            continue

        cleaned = sanitize_examples(parsed, forced_label=effective_label)
        if not cleaned:
            print("[WARN] Empty cleaned batch, skip.")
            continue

        remaining = args.target_size - (existing_count + total_added)
        rows_to_append: List[Dict[str, object]] = []

        for sample in cleaned:
            if len(rows_to_append) >= remaining:
                break
            sample_hash = hash_text(sample["text"])
            if sample_hash in known_hashes:
                continue

            row = {
                "text": sample["text"],
                "label": sample["label"],
            }
            rows_to_append.append(row)
            known_hashes.add(sample_hash)

        if not rows_to_append:
            print("[WARN] Batch had only duplicates/invalid items, continue.")
            continue

        append_jsonl_rows(output_file, rows_to_append)
        total_added += len(rows_to_append)

        elapsed = time.time() - started_at
        current_total = existing_count + total_added
        speed = current_total / elapsed if elapsed > 0 else 0.0
        eta_sec = (args.target_size - current_total) / speed if speed > 0 else float("inf")
        eta_msg = f"{eta_sec / 60:.1f} min" if eta_sec != float("inf") else "N/A"

        print(
            f"[INFO] Added {len(rows_to_append):2d} rows | total {current_total}/{args.target_size} | requests {request_count} | ETA {eta_msg}"
        )

        if args.manual_one_call and successful_calls >= 1:
            print("[INFO] Manual mode: completed 1 API call. Re-run script for the next call.")
            break

    final_total = existing_count + total_added
    if final_total >= args.target_size:
        print("[INFO] Completed target size.")
    else:
        print(f"[INFO] Stopped early at {final_total}/{args.target_size} rows.")
    print(f"[INFO] Final dataset file: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
