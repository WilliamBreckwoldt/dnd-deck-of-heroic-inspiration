# src/game_engine.py
import random
from .models import GameState, TrackedEntity
from .economy import die_and_resurrect
from .deck_manager import SECONDARY_DICE_MAP, DECK_DATA

def advance_time(state: GameState, days: int = 1):
    for _ in range(days):
        if state.game_over: break
        state.day_count += 1
        state.has_heroic_inspiration = True 
        
        for cat in ['buffs', 'curses', 'allies', 'enemies', 'loot']:
            target_dict = getattr(state, cat)
            expired = [k for k, v in list(target_dict.items()) if v.expiration_day and state.day_count >= v.expiration_day]
            for k in expired:
                del target_dict[k]
                state.log_event("⏳", f"{k} has expired after 1 year.")

        if state.active_beast_days > 0:
            state.active_beast_days -= 1
            if state.active_beast_days == 0:
                state.log_event("🧍", "You revert to humanoid form.")
        
        for transfer in state.pending_transfers:
            transfer["days"] -= 1
            if transfer["days"] == 0:
                state.party_gold += transfer["amount"]
                state.log_event("💰", f"{transfer['amount']:,} gp deposited to Party Wealth!")
        state.pending_transfers = [t for t in state.pending_transfers if t["days"] > 0]
        
        flames = state.enemies.get("Flames")
        if flames and random.random() < (flames.count * 0.05):
            state.log_event("👹", "AMBUSH! Devil assassin strikes!")
            die_and_resurrect(state)
            
        rogues = state.enemies.get("Rogue")
        if rogues and rogues.count > 3 and random.random() < ((rogues.count - 3) * 0.05):
            state.log_event("🗡️", "AMBUSH! Rogues assassinate you!")
            die_and_resurrect(state)
            
        undead = state.enemies.get("Undead")
        if undead and undead.count > 10 and random.random() < ((undead.count - 10) * 0.05):
            state.log_event("🧟", "AMBUSH! Revenant army strikes!")
            die_and_resurrect(state)

def commit_card_final(state: GameState, payload: dict = None):
    card = state.pending_card
    name = card["name"]
    sec = state.secondary_rolls
    data = payload or {}

    state.cards_drawn_count += 1
    state.log_event(card.get("emoji", "🃏"), f"{name}: {card.get('result_text', '')}")

    if card.get("is_destroyed_after_use", False):
        state.depleted_cards.append(name)

    match name:
        case "Aberration":
            if "Aberration" not in state.buffs:
                state.add_tracked("buffs", card)
            else:
                state.log_event("🐙", "Telepathy does not stack.")
        
        case "Balance":
            if data.get("c1") and data.get("c1") != "Skip":
                setattr(state, data["c1"], min(22, getattr(state, data["c1"]) + 2))
                new_dec = max(5, getattr(state, data["c2"]) - 2)
                setattr(state, data["c2"], new_dec)
                if state.intelligence < 3:
                    state.game_over = True
                    state.is_alive = False
                    state.game_over_reason = "Intelligence reduced below 3 (Feebleminded)."

        case "Beast":
            days = (sec[0] + sec[1]) if len(sec) >= 2 else 12
            state.active_beast_days += days
            advance_time(state, days)

        case "Book": 
            langs = (sec[0] + 2) if len(sec) >= 1 else 3
            state.add_tracked("buffs", card, details=f"+{langs} langs")

        case "Bridge": 
            new_casts = sec[0] if len(sec) >= 1 else 1
            curr = state.buffs.get("Bridge").count if "Bridge" in state.buffs else 0
            if new_casts > curr:
                desc = card.get("short_description") or card.get("description", "")
                state.buffs["Bridge"] = TrackedEntity(name="Bridge", emoji="🌉", description=desc, count=new_casts, details=[f"{new_casts} charges"])
                state.log_event("🌉", f"Time Stop charges set to {new_casts} (overrode {curr}).")
            else:
                state.log_event("🌉", f"Rolled {new_casts} Time Stop charges (kept higher {curr}).")

        case "Campfire": 
            state.has_heroic_inspiration = True

        case "Cavern": 
            state.climbing_speed = max(state.climbing_speed, state.walking_speed)

        case "Celestial": 
            state.flying_speed = max(state.flying_speed, 30)

        case "Comet": 
            if "Comet" not in state.buffs:
                state.add_tracked("buffs", card)

        case "Construct": 
            state.add_tracked("allies", card)

        case "Corpse": 
            advance_time(state, 1)

        case "Crossroads":
            if len(sec) >= 2:
                if sec[0] % 2 == 0:
                    state.age += sec[1]
                    state.log_event("⏳", f"Crossroads: Aged {sec[1]} years. (Now {state.age})")
                else:
                    state.age -= sec[1]
                    state.log_event("⏳", f"Crossroads: Grew {sec[1]} years younger. (Now {state.age})")
                
                if state.age < 13:
                    state.game_over = True
                    state.is_alive = False
                    state.game_over_reason = f"Perished of unnatural youth (Age {state.age} < 13)."
                elif state.age > 100:
                    state.game_over = True
                    state.is_alive = False
                    state.game_over_reason = f"Perished of extreme old age (Age {state.age} > 100)."

        case "Donjon": 
            state.game_over = True
            state.is_alive = False
            state.game_over_reason = "Imprisoned by Donjon in an extradimensional sphere."

        case "Door": 
            new_casts = sec[0] if len(sec) >= 1 else 1
            curr = state.buffs.get("Door").count if "Door" in state.buffs else 0
            if new_casts > curr:
                desc = card.get("short_description") or card.get("description", "")
                state.buffs["Door"] = TrackedEntity(name="Door", emoji="🚪", description=desc, count=new_casts, details=[f"{new_casts} charges"])
                state.log_event("🚪", f"Gate charges set to {new_casts} (overrode {curr}).")
            else:
                state.log_event("🚪", f"Rolled {new_casts} Gate charges (kept higher {curr}).")

        case "Dragon": 
            state.add_tracked("allies", card)

        case "Elemental":
            if data.get("c1"):
                if "Elemental" not in state.buffs:
                    state.add_tracked("buffs", card, specific_name="Elemental", details=data["c1"])
                else:
                    if data["c1"] not in state.buffs["Elemental"].details:
                        state.buffs["Elemental"].details.append(data["c1"])

        case "Euryale": 
            if "Euryale" not in state.curses:
                state.add_tracked("curses", card)

        case "Expert": 
            state.dexterity = min(22, state.dexterity + 2)

        case "Fates": 
            if "Fates" not in state.buffs:
                state.add_tracked("buffs", card)
            else:
                state.log_event("🪡", "Fates does not stack duplicate charges.")

        case "Fey":
            state.log_event("🧚", "Party casts Gate to retrieve you. Lost 1 day.")
            advance_time(state, 1)

        case "Fiend": 
            pass # Does nothing; not tracked as an enemy

        case "Flames": 
            state.add_tracked("enemies", card)

        case "Fool":
            advance_time(state, 3)

        case "Gem": 
            state.player_gold += 50000

        case "Giant":
            growth = (sec[0] + sec[1]) if len(sec) >= 2 else 10
            state.height_inches += growth
            state.max_hp_bonus += 20
            state.log_event("📏", f"Grew {growth} inches taller and gained +20 HP!")

        case "Humanoid": pass

        case "Jester": 
            advance_time(state, 3)

        case "Key": 
            state.add_tracked("loot", card)

        case "Knight": 
            state.add_tracked("allies", card)

        case "Lance":
            for attr in ['strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma']:
                setattr(state, attr, max(getattr(state, attr), min(20, getattr(state, attr) + 1)))

        case "Mage": 
            state.intelligence = min(22, state.intelligence + 2)

        case "Map": 
            state.add_tracked("buffs", card, duration=365)

        case "Maze": 
            advance_time(state, 1)

        case "Mine":
            if len(sec) >= 3: 
                state.player_gold += ((sec[0] + sec[1]) * 5000 + (sec[2] * 2500))

        case "Monstrosity": pass 

        case "Moon": 
            new_wishes = sec[0] if len(sec) >= 1 else 1
            curr = state.buffs.get("Moon").count if "Moon" in state.buffs else 0
            if new_wishes > curr:
                desc = card.get("short_description") or card.get("description", "")
                state.buffs["Moon"] = TrackedEntity(name="Moon", emoji="🌙", description=desc, count=new_wishes, details=[f"{new_wishes} wishes"])
                state.log_event("🌙", f"Wish charges set to {new_wishes} (overrode {curr}).")
            else:
                state.log_event("🌙", f"Rolled {new_wishes} Wishes (kept higher {curr}).")

        case "Ooze": pass 

        case "Path": 
            state.walking_speed += 10

        case "Pit": 
            advance_time(state, 1)

        case "Plant": 
            if "Plant" not in state.buffs:
                state.add_tracked("buffs", card)

        case "Priest": 
            state.wisdom = min(22, state.wisdom + 2)

        case "Prisoner": 
            advance_time(state, 1)

        case "Puzzle":
            stat_choice = data.get("c1") or "intelligence"
            loss = (sec[0] + 1) if len(sec) >= 1 else 2
            curr = getattr(state, stat_choice)
            actual_loss = curr - max(1, curr - loss)
            setattr(state, stat_choice, curr - actual_loss)
            
            state.puzzle_history.append({"stat": stat_choice, "amount": actual_loss})
            state.add_tracked("curses", card, specific_name="Puzzle", details=f"-{actual_loss} {stat_choice.upper()}")
            
            if state.intelligence < 3:
                state.game_over = True
                state.is_alive = False
                state.game_over_reason = "Intelligence reduced below 3 (Feebleminded)."

        case "Ring": 
            state.add_tracked("loot", card)

        case "Rogue": 
            state.add_tracked("enemies", card)

        case "Ruin": 
            # Track lost player gold AND lost pending transfers so Fates can reverse both
            lost_player_gold = state.player_gold
            lost_transfers = [t.copy() for t in state.pending_transfers]
            lost_transfer_amount = sum(t["amount"] for t in lost_transfers)
            total_gold_lost = lost_player_gold + lost_transfer_amount
            
            state.player_gold = 0
            state.pending_transfers = []
            state.ruin_history.append({
                "player_gold": lost_player_gold,
                "pending_transfers": lost_transfers,
                "total_lost": total_gold_lost
            })
            # Tooltip details now reflect the full combined loss
            state.add_tracked("curses", card, specific_name="Ruin", details=f"-{total_gold_lost:,} gp total lost")
            state.log_event("🏚️", f"All gold ({total_gold_lost:,} gp total: {lost_player_gold:,} gp on hand + {lost_transfer_amount:,} gp in escrow) disappeared!")

        case "Sage": 
            if "Sage" not in state.buffs:
                state.add_tracked("buffs", card, duration=365)
            else:
                state.buffs["Sage"].expiration_day = state.day_count + 365
                state.log_event("👴", "Sage: Expiration reset to 365 days from now.")

        case "Shield": 
            if "Shield" not in state.buffs:
                state.add_tracked("buffs", card, specific_name="Shield", details="AC 12 + DEX")
            else:
                state.log_event("🛡️", "Shield does not stack.")

        case "Ship":
            if "Ship" not in state.buffs or state.buffs["Ship"].count < 13:
                state.add_tracked("buffs", card, details="+3 skills")

        case "Skull":
            if random.random() < 0.05:
                state.log_event("💀", "Avatar of Death strikes you down!")
                die_and_resurrect(state)

        case "Staff": 
            state.add_tracked("loot", card)

        case "Stairway": 
            state.add_tracked("loot", card)

        case "Star": 
            chosen_stat = data.get("c1") or "strength"
            curr = getattr(state, chosen_stat)
            setattr(state, chosen_stat, min(24, curr + 2))
            state.log_event("⭐", f"Star increased {chosen_stat.title()} by 2 to {getattr(state, chosen_stat)}!")

        case "Statue": 
            advance_time(state, 1)

        case "Sun":
            # Loot stacks
            state.add_tracked("loot", card, specific_name="Sun (Magic Item)")
            # Buff does not stack
            if "Sun Temp HP" not in state.buffs:
                state.add_tracked("buffs", card, specific_name="Sun Temp HP", details="+10 Temp HP Daily")
            state.temp_hp = 10

        case "Talons": 
            state.game_over = True
            state.is_alive = False
            state.game_over_reason = "Talons disintegrated your magic items and the deck!"

        case "Tavern": 
            state.charisma = min(22, state.charisma + 2)

        case "Temple": 
            state.add_tracked("buffs", card, specific_name="Temple")

        case "Throne":
            if data.get("c1"):
                if "Throne" not in state.buffs:
                    state.add_tracked("buffs", card, specific_name="Throne", details=data["c1"])
                else:
                    if data["c1"] not in state.buffs["Throne"].details:
                        state.buffs["Throne"].details.append(data["c1"])

        case "Tomb": 
            if "Tomb" not in state.buffs:
                state.add_tracked("buffs", card, duration=365)
            else:
                state.buffs["Tomb"].expiration_day = state.day_count + 365
                state.log_event("⚰️", "Tomb: Expiration reset to 365 days from now.")

        case "Tower": pass

        case "Tree": 
            if "Tree" not in state.curses:
                state.add_tracked("curses", card)

        case "Undead": 
            state.add_tracked("enemies", card)

        case "Void": 
            state.game_over = True
            state.is_alive = False
            state.game_over_reason = "Soul drawn into the Void!"

        case "Warrior": 
            state.strength = min(22, state.strength + 2)

        case "Well":
            if "Well" not in state.buffs:
                state.add_tracked("buffs", card, details="+3 Cantrips")
                state.buffs["Well"].count = 3
            else:
                curr = state.buffs["Well"].count
                new_val = min(13, curr + 3)
                state.buffs["Well"].count = new_val
                state.buffs["Well"].details = [f"+{new_val} Cantrips"]

        case "Roll again": pass

def consume_charge(state: GameState, source: str, target: str):
    target_entity = None
    target_wish_stress = False
    target_divine = False

    if target == "Beast Form":
        beast_card = next((c for c in DECK_DATA if c["name"] == "Beast"), {})
        target_wish_stress = beast_card.get("causes_wish_stress", False)
        target_divine = beast_card.get("divine_intervention_removal", False)
    else:
        target_entity = state.curses.get(target) or state.enemies.get(target)
        if target_entity:
            target_wish_stress = target_entity.causes_wish_stress
            target_divine = target_entity.divine_intervention_removal

    # --- HANDLING FATES ON WISH STRESS ---
    if source == "Fates" and target == "Wish Stress":
        state.remove_tracked("buffs", "Fates")
        state.curses.pop("Wish Stress", None)
        state.wish_stressed = False

        # Gain 1 additional cast of Wish
        if "Moon" in state.buffs:
            state.buffs["Moon"].count += 1
            state.buffs["Moon"].details = [f"{state.buffs['Moon'].count} wishes"]
        else:
            moon_card = next((c for c in DECK_DATA if c["name"] == "Moon"), {})
            desc = moon_card.get("short_description") or moon_card.get("description", "")
            state.buffs["Moon"] = TrackedEntity(name="Moon", emoji="🌙", description=desc, count=1, details=["1 wishes"])

        # Re-apply whatever caused the Wish Stress
        stress_record = None
        for i in range(len(state.wish_removal_history) - 1, -1, -1):
            if state.wish_removal_history[i].get("caused_stress"):
                stress_record = state.wish_removal_history.pop(i)
                break
        
        if stress_record:
            orig_target = stress_record["target"]
            if orig_target == "Beast Form":
                state.active_beast_days = stress_record.get("beast_data", 12)
                state.log_event("🐾", "Wish Stress undone by Fates: Beast Form returned!")
            elif orig_target.startswith("Puzzle") or orig_target == "Puzzle":
                p_data = stress_record.get("puzzle_data")
                if p_data:
                    stat_name = p_data["stat"]
                    amt = p_data["amount"]
                    curr = getattr(state, stat_name)
                    setattr(state, stat_name, max(1, curr - amt))
                    state.puzzle_history.append(p_data)
                    puzzle_card = next((c for c in DECK_DATA if c["name"] == "Puzzle"), {})
                    state.add_tracked("curses", puzzle_card, specific_name="Puzzle", details=f"-{amt} {stat_name.upper()}")
                    state.log_event("🧩", f"Wish Stress undone by Fates: Puzzle returned (-{amt} {stat_name.upper()})!")
                    if state.intelligence < 3:
                        state.game_over = True
                        state.is_alive = False
                        state.game_over_reason = "Intelligence reduced below 3 (Feebleminded)."
            elif orig_target == "Ruin":
                r_data = stress_record.get("ruin_data")
                if r_data:
                    state.ruin_history.append(r_data)
                    state.player_gold = 0
                    state.pending_transfers = []
                    ruin_card = next((c for c in DECK_DATA if c["name"] == "Ruin"), {})
                    total_lost = r_data.get("total_lost", r_data["player_gold"])
                    state.add_tracked("curses", ruin_card, specific_name="Ruin", details=f"-{total_lost:,} gp total lost")
                    state.log_event("🏚️", "Wish Stress undone by Fates: Ruin returned (gold and escrow lost again)!")
            else:
                cat = stress_record.get("category", "curses")
                e_data = stress_record.get("entity_data")
                if e_data:
                    getattr(state, cat)[orig_target] = TrackedEntity(**e_data)
                    state.log_event(e_data.get("emoji", "⚠️"), f"Wish Stress undone by Fates: {orig_target} returned!")

        state.log_event("🪡", "Fates reversed Wish Stress! Regained 1 Wish, but the removed burden returned.")
        return

    # --- TEMPLE DIVINE INTERVENTION ---
    if source == "Temple":
        if not target_divine:
            state.log_event("🛕", f"Temple Divine Intervention cannot remove {target}!")
            return
        state.remove_tracked("buffs", "Temple")

    # --- WISH ---
    elif source == "Wish":
        if state.wish_stressed: return
        if "Moon" in state.buffs:
            state.buffs["Moon"].count -= 1
            if state.buffs["Moon"].count <= 0:
                del state.buffs["Moon"]
                state.log_event("🌙", "All Wish charges have been expended.")
            else:
                state.buffs["Moon"].details = [f"{state.buffs['Moon'].count} wishes"]

        # Snapshot removal history in case Fates undoes stress later
        stress_triggered = False
        if target_wish_stress:
            if random.random() < 0.33:
                stress_triggered = True

        record = {
            "target": target,
            "caused_stress": stress_triggered,
            "puzzle_data": state.puzzle_history[-1].copy() if (target.startswith("Puzzle") or target == "Puzzle") and state.puzzle_history else None,
            "ruin_data": state.ruin_history[-1].copy() if target == "Ruin" and state.ruin_history else None,
            "beast_data": state.active_beast_days if target == "Beast Form" else None,
            "entity_data": (state.curses.get(target) or state.enemies.get(target)).model_dump() if target not in ["Beast Form", "Ruin"] and not target.startswith("Puzzle") and (state.curses.get(target) or state.enemies.get(target)) else None,
            "category": "curses" if target in state.curses else "enemies"
        }
        state.wish_removal_history.append(record)

        if stress_triggered:
            state.wish_stressed = True
            state.curses["Wish Stress"] = TrackedEntity(name="Wish Stress", emoji="🌀", description="Cannot cast Wish ever again. Can be undone with Fates.")
            state.log_event("🌀", "Wish exertion has permanently stressed you!")

    # --- FATES NORMAL USE ---
    elif source == "Fates": 
        state.remove_tracked("buffs", "Fates")

    # Cleanse Target
    if target == "Beast Form": 
        state.active_beast_days = 0
    elif target.startswith("Puzzle") or target == "Puzzle":
        if state.puzzle_history:
            last = state.puzzle_history.pop()
            stat_name = last["stat"]
            amt = last["amount"]
            setattr(state, stat_name, getattr(state, stat_name) + amt)
            state.log_event("🧩", f"Restored +{amt} to {stat_name.title()} from Puzzle.")
        state.remove_tracked("curses", target)
    elif target == "Ruin":
        if state.ruin_history:
            last_ruin = state.ruin_history.pop()
            state.player_gold += last_ruin["player_gold"]
            state.pending_transfers.extend(last_ruin["pending_transfers"])
            total_restored = last_ruin.get("total_lost", last_ruin["player_gold"])
            state.log_event("💰", f"Restored {total_restored:,} gp total ({last_ruin['player_gold']:,} gp direct + {sum(t['amount'] for t in last_ruin['pending_transfers']):,} gp in transfers) from Ruin.")
        state.remove_tracked("curses", "Ruin")
    else: 
        state.remove_tracked("curses", target) or state.remove_tracked("enemies", target)
        
    state.log_event("✨", f"{source} cleansed: {target}")