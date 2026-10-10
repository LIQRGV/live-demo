# Live demo: "AI as your first employee"

9 messy WhatsApp messages → AI turns them into a spreadsheet → Python guardrails catch what the AI got wrong.

The AI only *reads*: each message becomes a product code and a quantity. Prices and totals always come from `katalog.csv` and are calculated by Python, in both acts. So every error you see comes from the AI misreading the chat, not from bad math.

## Run it

```bash
python demo.py --offline     # stage-safe, no internet needed (recommended on stage)
python demo.py --offline --naive   # Act 1 only
python demo.py               # live AI call (needs: pip install anthropic, ANTHROPIC_API_KEY)
```

No other packages needed. Outputs: `orders_naive.csv`, `orders_clean.csv`, `needs_review.csv` (open in Excel).

## Stage script (~10 min)

1. **Show `pesanan_wa.txt`** (1 min). "This is a real-looking Tuesday morning. Typos, Indonesian slang, a customer pressing send twice, a correction two hours later." Say once: the AI only reads; prices and totals are Python's job.
2. **Run Act 1** (2 min). AI produces a neat table in seconds. Point at the revenue: **Rp 1,755,000**. Ask the room: "Would you ship this to your finance team?"
3. **Pause and ask what's wrong** (2 min). Let the audience find problems: Pak Andi's duplicate, Mira's -85,000 row, Bu Rina's 1 kg *and* 2 kg, Fajar's Rp 0 question.
4. **Press Enter for Act 2** (2 min). Verified revenue: **Rp 1,575,000**. The AI-only version was off by **Rp 180,000 (~11%)** in nine messages: +225,000 duplicate, +40,000 correction, -85,000 typo.
5. **Walk through the 7 guards** (3 min). Each is 2–3 lines of plain Python:
   - A cut-off AI answer (`stop_reason == "max_tokens"`) is never processed (in `ask_ai()`)
   - Duplicate messages are skipped
   - Questions go to a human, not into the books
   - Product must exist in *our* catalog
   - Quantity must be a positive whole number
   - Price always comes from our catalog, never from the AI (a design rule, already true in Act 1)
   - A correction replaces the customer's earlier line instead of adding a second order, and is still listed for a human to confirm

**The line to land:** "The AI did the clerk's job in 5 seconds. Python is how you made sure the books weren't 11% off."

## Notes

- The AI was not stupid: it read "sepuluh" as 10, took Mira's "-1" literally (as written) and recognised both corrections. The failure was trusting its output without checks. That's the point.
- In live mode the AI's answer may differ from the saved one, so the Act 1 total can change between runs while Act 2 should stay at Rp 1,575,000. Rehearse with `--offline` and only go live if the venue wifi is solid.
- `ai_response_saved.json` matches the 9-message chat.
- Change the model with `DEMO_MODEL=... python demo.py`.
- Show the cut-off guard live (needs internet): `DEMO_MAX_TOKENS=100 python demo.py`. The AI stops after ~100 tokens, `stop_reason` is `"max_tokens"`, and the script stops with a clear message instead of processing half an answer. On Windows PowerShell: `$env:DEMO_MAX_TOKENS=100; python demo.py` (then `Remove-Item Env:DEMO_MAX_TOKENS`).
