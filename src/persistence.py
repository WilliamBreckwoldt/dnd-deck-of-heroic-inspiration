# src/persistence.py
import json
import os
from datetime import datetime
from .models import GameState

def save_high_score(state: GameState):
    """Calculates score and saves it to JSON."""
    if state.cards_drawn_count == 0: return

    score = (
        state.player_gold 
        + state.party_gold 
        + (state.strength + state.dexterity + state.constitution + state.intelligence + state.wisdom + state.charisma) * 100
        + (state.cards_drawn_count * 250)
        + (state.day_count * 10)
    )

    record = {
        "timestamp": datetime.now().isoformat(),
        "deck_size": state.deck_size,
        "end_reason": state.game_over_reason if state.game_over else "Voluntary Retirement",
        "days_survived": state.day_count,
        "cards_drawn": state.cards_drawn_count,
        "total_gold": state.player_gold + state.party_gold,
        "score": score
    }

    path = os.path.join("data", "high_scores.json")
    
    # Initialize if missing
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({"deck_13": [], "deck_22": [], "deck_66": []}, f)
            
    with open(path, "r") as f:
        data = json.load(f)

    deck_key = f"deck_{state.deck_size}"
    if deck_key not in data: data[deck_key] = []
    
    data[deck_key].append(record)
    # Sort descending by score
    data[deck_key] = sorted(data[deck_key], key=lambda x: x["score"], reverse=True)

    with open(path, "w") as f:
        json.dump(data, f, indent=4)
        
    return record