"""
Τρέχει μέσα στο GitHub Actions κάθε μέρα.
Τραβάει τιμές μετοχών από το yfinance και προσθέτει μία γραμμή ανά μετοχή
στο αρχείο prices.csv (μέσα στο ίδιο repository).

Η ημερομηνία που καταγράφεται είναι η ημερομηνία της τελευταίας
ολοκληρωμένης συνεδρίασης όπως επιστρέφεται από το yfinance,
ΟΧΙ η σημερινή ημερομηνία εκτέλεσης.

--- BUGFIX (14/07/2026) ---
Παλιότερα, όταν το yfinance επέστρεφε ημιτελή/κενή τελευταία γραμμή
ιστορικού (π.χ. αν το GitHub Actions έτρεχε πολύ νωρίς, πριν προλάβει το
Yahoo να "οριστικοποιήσει" το κλείσιμο της ημέρας για όλα τα σύμβολα), ο
κώδικας έγραφε τη γραμμή ΚΑΙ ΜΕ NaN Price — δεν υπήρχε έλεγχος εγκυρότητας.
Αυτό προκάλεσε 21 από τα 35 σύμβολα να μείνουν με κενή τιμή στις 14/07.
Τώρα κάνουμε dropna() στο Close ΠΡΙΝ διαλέξουμε "τελευταία/προτελευταία
τιμή", ώστε να παίρνουμε πάντα την πιο πρόσφατη ΠΛΗΡΗ συνεδρίαση — αν η
τελευταία μέρα είναι ημιτελής, απλά χρησιμοποιούμε την προηγούμενη πλήρη
(και η επόμενη εκτέλεση θα προσθέσει κανονικά τη μέρα που έλειψε, μόλις
οριστικοποιηθεί). Προστέθηκε επίσης retry για το t.info (πιο ασταθές API
από το t.history), που εξηγούσε τα κενά Name.
"""

import csv
import os
import time

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


def load_existing_dates():
    if not os.path.exists(CSV_PATH):
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["Date"] for row in reader}


def fetch_history_clean(ticker):
    """t.history() με retry, ΚΑΙ dropna στο Close ώστε να μην πάρουμε ποτέ
    ημιτελή/κενή τελευταία γραμμή σαν να ήταν η 'τρέχουσα τιμή'."""
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d").dropna(subset=["Close"])
            if not hist.empty and len(hist) >= 2:
                return t, hist
            last_error = "ανεπαρκή δεδομένα (μετά την αφαίρεση ημιτελών γραμμών)"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(last_error)


def fetch_name(t):
    """t.info με retry — πιο ασταθές/αργό API από το t.history, εξηγούσε τα
    κενά Name που είδαμε (π.χ. UEC, O, CCJ, AMD, V, KO στις 17/07)."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            name = t.info.get("shortName", "") or ""
            if name:
                return name
        except Exception:
            pass
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)
    return ""  # αν αποτύχει και μετά τα retries, μένει κενό — το dashboard
               # ήδη το καλύπτει με fallback στο watchlist.csv


def main():
    existing_dates = load_existing_dates()
    file_exists = os.path.exists(CSV_PATH)
    rows_written = 0
    skipped = []
    session_date = None  # θα οριστεί από την πρώτη μετοχή

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Symbol", "Name", "Price", "Prev Close", "Change %"])

        for sym in SYMBOLS:
            ticker = sym.replace(".", "-")
            try:
                t, hist = fetch_history_clean(ticker)

                # Ημερομηνία από το index του yfinance (τελευταία ΠΛΗΡΗΣ συνεδρίαση)
                trade_date = hist.index[-1].strftime("%d/%m/%Y")

                # Αρχικοποίηση session_date από την πρώτη μετοχή
                if session_date is None:
                    session_date = trade_date
                    if trade_date in existing_dates:
                        print(f"Υπάρχουν ήδη δεδομένα για {trade_date}. Δεν θα προστεθούν διπλότυπα.")
                        return

                price = round(float(hist["Close"].iloc[-1]), 4)
                prev_close = round(float(hist["Close"].iloc[-2]), 4)
                change_pct = round((price - prev_close) / prev_close, 6)
                name = fetch_name(t)
            except Exception as e:
                print(f"Σφάλμα στο {sym}: {e}")
                skipped.append(sym)
                continue

            writer.writerow([trade_date, sym, name, price, prev_close, change_pct])
            rows_written += 1

    print(f"Προστέθηκαν {rows_written} γραμμές για {session_date}.")
    if skipped:
        print(f"⚠️  Παραλείφθηκαν {len(skipped)} σύμβολα (θα ξαναδοκιμαστούν στην επόμενη εκτέλεση): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
