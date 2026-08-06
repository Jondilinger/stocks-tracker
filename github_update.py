"""
Τρέχει μέσα στο GitHub Actions κάθε μέρα.
Τραβάει τιμές μετοχών από το yfinance και προσθέτει γραμμές στο prices.csv.

--- REWRITE (05/08/2026) — self-healing backfill ---
Η παλιά λογική έλεγχε ΜΟΝΟ "τη σημερινή συνεδρίαση": έπαιρνε το
session_date από το ΠΡΩΤΟ σύμβολο της λίστας (BRLT) και, αν αυτή η
ημερομηνία υπήρχε ήδη στο CSV, έκανε return αμέσως — για ΟΛΑ τα
σύμβολα. Αν το BRLT (μικρή/ασταθής μετοχή) είχε ημιτελές ιστορικό
εκείνη τη μέρα (halt, χαμηλή ρευστότητα, καθυστέρηση στο yfinance),
το script νόμιζε ότι δεν υπήρχε νέα μέρα και σταματούσε — ενώ τα
άλλα 34 σύμβολα είχαν κανονικά δεδομένα. Αποτέλεσμα: μόνιμα κενά
στο prices.csv (π.χ. 24/07, 28/07, 03/08/2026) χωρίς κανένα error —
το GitHub Actions run εμφανιζόταν "Success".

Τώρα η λογική είναι ανά-σύμβολο και αυτο-επουλωτική:
  - Για κάθε σύμβολο, τραβάμε ιστορικό ~1 μήνα (αρκετό ώστε ακόμα κι
    αν έχει χαθεί μια εκτέλεση για μέρες, να καλυφθεί στην επόμενη).
  - Υπολογίζουμε Prev Close μέσα στο ίδιο ιστορικό (shift), όχι μόνο
    από την τελευταία μέρα.
  - Γράφουμε ΜΟΝΟ τις (ημερομηνία, σύμβολο) γραμμές που ΔΕΝ υπάρχουν
    ήδη στο CSV — ανεξάρτητα από το τι συνέβη σε άλλα σύμβολα.
  - Έτσι μια κολλημένη/ημιτελής μετοχή δεν μπλοκάρει πια τις άλλες,
    και ένα χαμένο run διορθώνεται μόνο του στο επόμενο επιτυχημένο.
"""

import csv
import os
import time

import pandas as pd
import yfinance as yf

SYMBOLS = [
    "BRLT", "UEC", "SMR", "QBTS", "RGTI", "IONQ", "O", "NBIS", "OKLO", "CCJ",
    "ANET", "NVDA", "AMD", "ABBV", "AAPL", "TSM", "GOOGL", "V", "MSFT", "META",
    "BABA", "AMZN", "ASML", "ASTS", "BRK.B", "ENS", "INTC", "MRVL", "MELI",
    "PLTR", "PEP", "SOFI", "TSLA", "KO", "UNH",
]

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.csv")

RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5

# Πόσο πίσω κοιτάμε ανά εκτέλεση. Αρκετό ώστε να καλύψει ακόμα και
# αρκετές συνεχόμενες χαμένες εκτελέσεις (π.χ. διακοπές, tokens κλπ.).
LOOKBACK_PERIOD = "1mo"


def load_existing_pairs():
    """Επιστρέφει set από (Date, Symbol) tuples που υπάρχουν ήδη στο CSV."""
    if not os.path.exists(CSV_PATH):
        return set(), []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    pairs = {(r["Date"], r["Symbol"]) for r in rows}
    return pairs, rows


def fetch_history_clean(ticker):
    """t.history() με retry, dropna στο Close ώστε να μη μείνουν ημιτελείς/κενές γραμμές."""
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=LOOKBACK_PERIOD).dropna(subset=["Close"])
            if not hist.empty and len(hist) >= 2:
                return t, hist
            last_error = "ανεπαρκή δεδομένα (μετά την αφαίρεση ημιτελών γραμμών)"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(last_error)


def fetch_name(t):
    """t.info με retry — πιο ασταθές/αργό API από το t.history."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            name = t.info.get("shortName", "") or ""
            if name:
                return name
        except Exception:
            pass
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)
    return ""  # μένει κενό — το dashboard το καλύπτει με fallback στο watchlist.csv


def main():
    existing_pairs, existing_rows = load_existing_pairs()

    new_rows = []
    skipped = []

    for sym in SYMBOLS:
        ticker = sym.replace(".", "-")
        try:
            t, hist = fetch_history_clean(ticker)
        except Exception as e:
            print(f"Σφάλμα στο {sym}: {e}")
            skipped.append(sym)
            continue

        # Prev Close υπολογισμένο ΜΕΣΑ στο ίδιο ιστορικό (όχι μόνο τελευταία γραμμή)
        hist = hist.copy()
        hist["PrevClose"] = hist["Close"].shift(1)

        # Ποιες μέρες από αυτό το ιστορικό λείπουν ήδη από το CSV για ΑΥΤΟ το σύμβολο
        missing_dates = [
            idx for idx in hist.index
            if (idx.strftime("%d/%m/%Y"), sym) not in existing_pairs
        ]
        # Χρειαζόμαστε Prev Close, άρα αγνοούμε την πρώτη γραμμή του window αν δεν έχει
        missing_dates = [d for d in missing_dates if pd.notna(hist.loc[d, "PrevClose"])]

        if not missing_dates:
            continue  # όλα ήδη καταγεγραμμένα για αυτό το σύμβολο, κανονικό

        name = fetch_name(t)

        for d in sorted(missing_dates):
            price = round(float(hist.loc[d, "Close"]), 4)
            prev_close = round(float(hist.loc[d, "PrevClose"]), 4)
            change_pct = round((price - prev_close) / prev_close, 6)
            new_rows.append({
                "Date": d.strftime("%d/%m/%Y"),
                "Symbol": sym,
                "Name": name,
                "Price": price,
                "Prev Close": prev_close,
                "Change %": change_pct,
            })
            print(f"  + {sym} {d.strftime('%d/%m/%Y')}: {price} (prev {prev_close})")

    if not new_rows:
        print("Καμία νέα γραμμή — όλα τα σύμβολα είναι ήδη ενημερωμένα.")
    else:
        all_rows = existing_rows + new_rows
        # Ταξινόμηση χρονολογικά, μετά αλφαβητικά ανά σύμβολο, για καθαρό αρχείο
        all_rows.sort(key=lambda r: (
            pd.to_datetime(r["Date"], dayfirst=True), r["Symbol"]
        ))
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["Date", "Symbol", "Name", "Price", "Prev Close", "Change %"]
            )
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nΠροστέθηκαν {len(new_rows)} νέες γραμμές συνολικά (backfill + σήμερα).")

    if skipped:
        print(f"⚠️  Παραλείφθηκαν {len(skipped)} σύμβολα (θα ξαναδοκιμαστούν στην επόμενη εκτέλεση): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
