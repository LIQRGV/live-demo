"""
LIVE DEMO: "AI as your first employee"
--------------------------------------
Messy WhatsApp orders  ->  AI reads them  ->  clean spreadsheet.
Then the twist: Python guardrails catch what the AI quietly got wrong.

Usage:
    pip install anthropic          # only needed for live mode
    export ANTHROPIC_API_KEY=...    # only needed for live mode

    python demo.py                  # live: calls the AI
    python demo.py --offline        # stage-safe: replays a saved AI response
    python demo.py --naive          # Act 1 only: trust the AI blindly
"""

import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
MODEL = os.environ.get("DEMO_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(os.environ.get("DEMO_MAX_TOKENS", "16000"))  # set to 100 on stage to show the cut-off guard


# ---------------------------------------------------------------------------
# 1. Load the inputs: raw chat + product catalog
# ---------------------------------------------------------------------------
@dataclass
class Message:
    id: int        # position in the chat, the AI refers to it as msg_id
    time: str
    sender: str
    text: str


@dataclass
class Product:
    code: str
    name: str
    unit: str
    price: int     # converted to a number once, here, not every time we use it


@dataclass
class ReviewItem:
    """One line a human must look at: who, what, and why a guardrail stopped it."""
    customer: str
    reason: str
    product: str = "-"   # "-" when the whole message was flagged, not one product
    qty: object = "-"    # may be whatever the AI returned (None, 0.5, ...), that is the point

    def row(self):
        return [self.customer, self.product, self.qty, self.reason]


def load_messages():
    """Chat lines -> list of Message, in chat order."""
    lines = (HERE / "pesanan_wa.txt").read_text(encoding="utf-8").strip().splitlines()
    msgs = []
    for i, line in enumerate(lines):
        m = re.match(r"\[(.+?)\]\s*(.+?):\s*(.+)", line)
        if m:
            msgs.append(Message(id=i, time=m[1], sender=m[2], text=m[3].strip()))
    return msgs


def load_catalog():
    """CSV rows -> {code: Product}, keyed by code because we always look products up by code."""
    with open(HERE / "katalog.csv", encoding="utf-8") as f:
        return {
            row["kode"]: Product(code=row["kode"], name=row["nama"], unit=row["satuan"], price=int(row["harga"]))
            for row in csv.DictReader(f)
        }


# ---------------------------------------------------------------------------
# 2. Ask the AI to turn chat into structured orders
# ---------------------------------------------------------------------------
PROMPT = """You are an order clerk for a small Makassar shop.
Catalog (code: name, unit):
{catalog}

Read each WhatsApp message below and extract orders.
Return ONLY a JSON list. One object per message:
- msg_id: the message number (the # in front of it)
- customer: the sender's name
- kind: "new" for a new order, "correction" if it changes an earlier order,
  or "question" if they are only asking
- items: a list of the products ordered, each with:
    - code: the catalog code, or null if the product is not in the catalog
    - product_text: the product in the customer's own words
    - qty: how many, as a number
  For a correction, list only the changed products, each with its corrected final qty.
- note: anything else worth knowing (address, pickup time, ...), written in Indonesian

Messages:
{messages}
"""


def ask_ai(messages, catalog):
    import anthropic  # imported here so --offline works without the package

    cat_text = "\n".join(f"{p.code}: {p.name}, {p.unit}" for p in catalog.values())
    msg_text = "\n".join(f"#{m.id} [{m.time}] {m.sender}: {m.text}" for m in messages)

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": PROMPT.format(catalog=cat_text, messages=msg_text)}],
    )
    # breakpoint()
    # Guard 0: a cut-off answer is never processed (half a JSON list = missing orders)
    if resp.stop_reason == "max_tokens":
        raise SystemExit(
            f"\nSTOPPED: the AI answer was cut off at max_tokens={MAX_TOKENS} "
            f"(stop_reason='max_tokens').\nNothing was processed. Raise max_tokens and run again."
        )
    # content can start with a thinking block, so pick the text block by type
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text[text.find("["): text.rfind("]") + 1])


def ask_ai_offline():
    """A saved, realistic AI response, so the demo never dies on stage wifi."""
    return json.loads((HERE / "ai_response_saved.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 3a. ACT 1 — the naive version: trust the AI, write the spreadsheet
# ---------------------------------------------------------------------------
def naive(ai_orders, catalog):
    rows = []
    for o in ai_orders:
        for it in o["items"]:
            price = catalog[it["code"]].price if it["code"] in catalog else 0
            qty = it["qty"] or 0  # the AI sometimes leaves qty empty (null)
            rows.append([o["customer"], it["product_text"], qty, price * qty])
    write_csv("orders_naive.csv", ["customer", "product", "qty", "total"], rows)
    print_table("ACT 1: AI did the clerk's job", ["customer", "product", "qty", "total"], rows)
    total = sum(r[3] for r in rows)
    print(f"  Revenue today: Rp {total:,.0f}   <- looks great. Is it right?\n")


# ---------------------------------------------------------------------------
# 3b. ACT 2 — the production version: Python guardrails
# ---------------------------------------------------------------------------
def guarded(ai_orders, catalog, messages):
    by_id = {m.id: m for m in messages}
    seen_texts = set()
    ok, review = [], []
    placed = {}  # (sender, product code) -> position of that line in ok

    for o in ai_orders:
        src = by_id.get(o["msg_id"])
        sender = src.sender if src else None
        key = (sender, src.text if src else None)

        # Guard 1: duplicate message (customer pressed send twice)
        if key in seen_texts:
            review.append(ReviewItem(o["customer"], "DUPLICATE message, skipped"))
            continue
        seen_texts.add(key)

        # Guard 2: questions (and anything with no usable items) need a human, not an order
        if o["kind"] not in ("new", "correction") or not o["items"]:
            review.append(ReviewItem(o["customer"], f"{o['kind'].upper()}: {o.get('note', '')}"))
            continue

        for it in o["items"]:
            code, qty = it["code"], it["qty"]
            line = (sender, code)
            # Guard 3: product must exist in OUR catalog, not the AI's imagination
            if code not in catalog:
                review.append(ReviewItem(o["customer"], "NOT IN CATALOG", it["product_text"], qty))
                continue
            # Guard 4: quantity must be a positive whole number
            if not isinstance(qty, (int, float)) or qty <= 0 or qty != int(qty):
                review.append(ReviewItem(o["customer"], "BAD QUANTITY", it["product_text"], qty))
                continue
            # Guard 5: price ALWAYS comes from our catalog, never from the AI
            product = catalog[code]
            row = [o["customer"], product.name, int(qty), product.price * int(qty)]
            # Guard 6: a correction REPLACES the customer's earlier line, it is not a second order
            if o["kind"] == "correction":
                if line in placed:
                    old_qty = ok[placed[line]][2]
                    ok[placed[line]] = row
                    review.append(ReviewItem(o["customer"], f"CORRECTION applied: qty {old_qty} -> {row[2]}, please confirm", row[1], row[2]))
                    continue
                # the line it corrects was never approved (e.g. a typo'd qty): take it as the order
                review.append(ReviewItem(o["customer"], "CORRECTION taken as the order (no valid earlier line), please confirm", row[1], row[2]))
            placed[line] = len(ok)
            ok.append(row)

    write_csv("orders_clean.csv", ["customer", "product", "qty", "total"], ok)
    review_rows = [r.row() for r in review]
    write_csv("needs_review.csv", ["customer", "product", "qty", "reason"], review_rows)

    print_table("ACT 2: Approved orders", ["customer", "product", "qty", "total"], ok)
    print(f"  Verified revenue: Rp {sum(r[3] for r in ok):,.0f}\n")
    print_table("Sent to a human for review", ["customer", "product", "qty", "reason"], review_rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def write_csv(name, header, rows):
    with open(HERE / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def print_table(title, header, rows):
    print(f"\n=== {title} ===")
    cells = [header] + [[f"{c:,}" if isinstance(c, int) and abs(c) > 999 else str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    for n, r in enumerate(cells):
        print("  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)))
        if n == 0:
            print("  " + "  ".join("-" * w for w in widths))


def main():
    messages, catalog = load_messages(), load_catalog()
    print(f"Read {len(messages)} WhatsApp messages, {len(catalog)} products in catalog.")

    if "--offline" in sys.argv:
        ai_orders = ask_ai_offline()
    else:
        print(f"Asking the AI ({MODEL})...")
        ai_orders = ask_ai(messages, catalog)

    naive(ai_orders, catalog)
    if "--naive" in sys.argv:
        return

    input("Press Enter for Act 2 (the guardrails)... ")

    if sys.stdout.isatty():
        print("\033[2J\033[H", end="", flush=True)  # clear the screen

    guarded(ai_orders, catalog, messages)


if __name__ == "__main__":
    main()
