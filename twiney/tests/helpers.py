"""Shared fixtures for TWINEY tests."""

from twiney.book import ASK, BID, DELETE, INSERT, UPDATE, Book
from twiney.config import build_config

PLAYS = [
    {"symbol": "AAA", "side": "long", "trigger": 10.00, "second_entry": 10.10},
    {"symbol": "BBB", "side": "short", "trigger": 50.00, "second_entry": 49.60},
    {"symbol": "CCC", "side": "long", "trigger": 20.00, "second_entry": 20.20},
    {"symbol": "DDD", "side": "long", "trigger": 5.00, "second_entry": 5.05},
]


def cfg(**sections):
    raw = {"reload": {"auto_levels": False}}
    for name, values in sections.items():
        raw.setdefault(name, {}).update(values)
    return build_config(raw)


def plays():
    from twiney.config import validate_plays
    return validate_plays({"plays": [dict(p) for p in PLAYS]})


def ladder(book, side, rows):
    """Insert rows [(price, size), ...] best-first on one side."""
    for i, (price, size) in enumerate(rows):
        book.apply(i, INSERT, side, price, size, "")


def seller_book(ask0=1000):
    book = Book(rows_requested=10)
    ladder(book, BID, [(9.99, 500), (9.98, 400)])
    ladder(book, ASK, [(10.00, ask0), (10.01, 800), (10.02, 900)])
    return book


__all__ = ["ASK", "BID", "INSERT", "UPDATE", "DELETE", "Book", "cfg", "plays", "ladder", "seller_book", "PLAYS"]
