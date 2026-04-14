Dat API key (PowerShell):


Muc tieu: moi lenh ben duoi se chay full de tao file 2000 prompts.

1) Gemini 2.5 Flash - Label 1:
python gendata/generate_gemini_dataset.py --meta-prompt-file gendata/label1metaprompt.md --force-label 1 --model gemini-2.5-flash --target-size 2000 --rpm 3 --examples-per-call 25 --output-file gendata/generated_label1_2000.jsonl

2) Gemini 2.5 Flash - Label 2:
python gendata/generate_gemini_dataset.py --meta-prompt-file gendata/label2metaprompt.md --force-label 2 --model gemini-2.5-flash --target-size 2000 --rpm 3 --examples-per-call 25 --output-file gendata/generated_label2_2000.jsonl

3) Gemini 3 Flash - Label 1:
python gendata/generate_gemini_dataset.py --meta-prompt-file gendata/label1metaprompt.md --force-label 1 --model gemini-3-flash-preview --target-size 2000 --rpm 3 --examples-per-call 25 --output-file gendata/generated_label1_2000.jsonl

4) Gemini 3 Flash - Label 2:
python gendata/generate_gemini_dataset.py --meta-prompt-file gendata/label2metaprompt.md --force-label 2 --model gemini-3-flash-preview --target-size 2000 --rpm 3 --examples-per-call 25 --output-file gendata/generated_label2_2000.jsonl

Luu y:
- Voi --examples-per-call 25, ly thuyet can ~80 requests de dat 2000 prompts.
- Thuc te co the can them requests neu bi duplicate/invalid hoac model tra ve thieu so luong.