# src/economy.py
import random
from .models import GameState

def die_and_resurrect(state: GameState):
    state.log_event("💀", "You died!")
    if "Temple" in state.buffs:
        state.remove_tracked("buffs", "Temple")
        state.log_event("✨", "Your bound deity intervened! Free resurrection!")
        cleanse_death_effects(state)
        return
        
    cost = 1000
    if state.player_gold >= cost:
        state.player_gold -= cost
        state.log_event("💸", f"Paid {cost:,} gp from Player Wealth for resurrection.")
    elif (state.player_gold + state.party_gold) >= cost:
        remainder = cost - state.player_gold
        state.player_gold = 0
        state.party_gold -= remainder
        state.log_event("💸", f"Paid {cost:,} gp using Party Wealth for resurrection.")
    else:
        state.is_alive = False
        state.game_over = True
        state.game_over_reason = "Killed and couldn't afford Resurrection."
        state.log_event("⚰️", "GAME OVER: Insufficient funds for resurrection.")
        return
    cleanse_death_effects(state)

def cleanse_death_effects(state: GameState):
    if "Flames" in state.enemies:
        del state.enemies["Flames"]
        state.log_event("🔥", "Death severed your enmity with the devils.")
    if "Sun Temp HP" in state.buffs:
        del state.buffs["Sun Temp HP"]
        state.temp_hp = 0
    if "Fates" in state.buffs:
        del state.buffs["Fates"]
        state.log_event("🪡", "Your Fates protection was lost upon death.")

def queue_gold_transfer(state: GameState):
    amt = state.player_gold
    if amt <= 0: return
    state.player_gold = 0
    delay = random.randint(1, 6) + 1
    state.pending_transfers.append({"amount": amt, "days": delay})
    state.log_event("🏦", f"Transfer of {amt:,} gp queued. Paperwork takes {delay} days.")