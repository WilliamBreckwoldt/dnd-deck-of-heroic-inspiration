# src/deck_manager.py
import json, random, os
from .models import D100Roll

SECONDARY_DICE_MAP = {
    "Bridge": [3], "Crossroads": [20, 10], "Door": [4],
    "Giant": [10, 10], "Maze": [3], "Mine": [6, 6, 10],
    "Moon": [3], "Pit": [6, 6, 6], "Puzzle": [4], "Beast": [12, 12], "Book": [6]
}

def load_deck() -> list[dict]:
    path = os.path.join("data", "deck.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

DECK_DATA = load_deck()

def roll_secondary(dice_types: list[int]) -> list[int]:
    return [random.randint(1, sides) for sides in dice_types]

def get_card_for_roll(deck_cards: list[dict], roll: D100Roll, deck_size: int, depleted: list[str]) -> dict:
    val = roll.total
    deck_key = f"{deck_size}_card_deck"
    for card in deck_cards:
        if card["name"] in depleted: continue
        ranges = card.get("roll_ranges", {}).get(deck_key)
        if ranges and ranges["min"] <= val <= ranges["max"]:
            return card
    return next(c for c in deck_cards if c["name"] == "Roll again")

def get_valid_d100(deck_size: int, depleted: list[str], avoid_names: list[str] = None) -> D100Roll:
    """Rolls a d100. Any result from 1-100 is valid (67-100 maps to 'Roll again' on the 66-card deck)."""
    avoid = avoid_names or []
    while True:
        r = D100Roll(tens=random.randint(0, 9), units=random.randint(0, 9))
        c = get_card_for_roll(DECK_DATA, r, deck_size, depleted)
        if c["name"] in avoid: 
            continue
        return r