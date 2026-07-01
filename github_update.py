"""
Τρέχει μέσα στο GitHub Actions κάθε μέρα.
Τραβάει τιμές μετοχών από το yfinance και προσθέτει μία γραμμή ανά μετοχή
στο αρχείο prices.csv (μέσα στο ίδιο repository).

Η ημερομηνία που καταγράφεται είναι η ημερομηνία της τελευταίας
ολοκληρωμένης συνεδρίασης όπως επιστρέφεται από το yfinance,
ΟΧΙ η σημερινή ημερομηνία εκτέλεσης.
"""

import csv
import os

import yfinance as yf

SYMBOLS = [
    "BRLT", "UEC", "SMR", "QBTS", "RGTI", "IONQ", "O", "NBIS", "OKLO", "CCJ",
    "ANET", "NVDA", "AMD", "ABBV", "AAPL", "TSM", "GOOGL", "V", "MSFT", "META",
    "BABA", "AMZN", "ASML", "ASTS", "BRK.B", "ENS", "INTC", "MRVL", "MELI",
    "PLTR", "PEP", "SOFI", "TSLA", "KO", "UNH",
]

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.csv")


def load_existing_dates():
    if not os.path.exists(CSV_PATH):
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["Date"] for row in reader}


def main():
    existing_dates = load_existing_dates()
    file_exists = os.path.exists(CSV_PATH)
    rows_written = 0
    session_date = None  # θα οριστεί από την πρώτη μετοχή

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Symbol", "Name", "Price", "Prev Close", "Change %"])

        for sym in SYMBOLS:
            ticker = sym.replace(".", "-")
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if hist.empty or len(hist) < 2:
                    print(f"Παράλειψη {sym}: ανεπαρκή δεδομένα")
                    continue

                # Ημερομηνία από το index του yfinance (τελευταία κλειστή συνεδρίαση)
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
                try:
                    name = t.info.get("shortName", "") or ""
                except Exception:
                    name = ""
            except Exception as e:
                print(f"Σφάλμα στο {sym}: {e}")
                continue

            writer.writerow([trade_date, sym, name, price, prev_close, change_pct])
            rows_written += 1

    print(f"Προστέθηκαν {rows_written} γραμμές για {session_date}.")


if __name__ == "__main__":
    main()
