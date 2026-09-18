# 🃏 D&D Deck of Many (and Many More) Things Simulator

An interactive, animated web application running directly inside a Jupyter Notebook simulating a D&D character drawing from the **Deck of Many Things** and **Deck of Many More Things** across 13-, 22-, and 66-card variants.

---

## 1. Quick Start

### Prerequisites
- Python 3.10+
- Jupyter Notebook or JupyterLab

### Installation
```bash
pip install -r requirements.txt
```

### Launching the Application
Open `run_game.ipynb` and run the cell:
```python
import threading
import uvicorn
import time
from IPython.display import IFrame, display, HTML
from src.server import app

def start_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="critical")

thread = threading.Thread(target=start_server, daemon=True)
thread.start()
time.sleep(1.5)

display(HTML("<h3><a href='http://127.0.0.1:8000' target='_blank'>➡️ Click here to open in a new tab</a></h3>"))
display(IFrame(src="http://127.0.0.1:8000", width="100%", height="1000px"))
```

---

## 2. Architecture & Tech Stack

```text
deck-of-many-things-sim/
│
├── run_game.ipynb           # Entrypoint: spins up FastAPI daemon thread & renders iframe
├── requirements.txt         # Dependencies (fastapi, uvicorn, pydantic)
├── README.md                # System specification & developer manual
│
├── data/
│   ├── deck.json            # 66-card database with ranges, emojis, flags, descriptions
│   └── high_scores.json     # Saved run records
│
└── src/
    ├── __init__.py
    ├── models.py            # Pydantic schemas: D100Roll, TrackedEntity, GameState
    ├── deck_manager.py      # Card lookup tables, roll generators, secondary dice map
    ├── economy.py           # Gold tracking, escrow transfers, death & resurrection
    ├── game_engine.py       # Switch-case card resolver, time engine, ambushes, cures
    └── server.py            # FastAPI REST endpoints + self-contained Vue 3 SPA
```

### Why FastAPI + Vue 3 (No Node/Build Step Required)?
- **Real-Time Client-Side Animations:** Pure CSS and Vue client-side timers handle 60fps dice-rolling animations and countdowns without server latency or WebSocket desync.
- **Self-Contained Single-File Frontend:** Vue 3 and Tailwind CSS are loaded via CDN directly within `src/server.py` as an `HTMLResponse`, eliminating all static file-path errors in Jupyter.
- **Standardized State Machine:** The backend acts as a deterministic state machine; the frontend renders views based on `modal_phase`.

---

## 3. Character Attributes & Mechanical Formulas

| Attribute | Baseline | Calculation / Rules |
| :--- | :--- | :--- |
| **Ability Scores** | `10` | STR, DEX, CON, INT, WIS, CHA. Min: 1. Max: 20 (Lance), 22 (Standard cards), 24 (Star). |
| **Feeblemind Death** | `INT < 3` | If Intelligence drops below 3 (e.g., via *Puzzle*), the character becomes vegetative; **Game Over**. |
| **Hit Points (HP)** | `54` | Formula: `(CON modifier * 13) + 54 + max_hp_bonus`. CON mod = `(CON - 10) // 2`. |
| **Temporary HP** | `0` | Granted by *Sun*. Appended cleanly as `(+10)` at the end of HP. Stripped upon death. |
| **Age** | `25` | Modified by *Crossroads* (1d10). **If Age < 13 or Age > 100: Character dies; Game Over.** |
| **Height** | `68 in` | 5'8" baseline. Increased by *Giant* (2d10 inches). Formatted as `5'8" (68 in)`. |
| **Speeds** | `30 ft` | Base walk: 30 ft (+10 per *Path*). Climb: equal to walk (*Cavern*). Fly: 30 ft (*Celestial*). |

---

## 4. Economy & Resurrection Mechanics

### Currency Pools
- **Player Wealth:** Starts at `5,000 gp`. Carried on person; vulnerable to *Ruin*.
- **Party Wealth:** Starts at `15,000 gp`. Stored safely; immune to *Ruin*.

### Gold Transfer (Paperwork Escrow)
- **"Transfer ALL Gold" Button:** Moves all player gold into escrow. Takes `1d6 + 1` in-game days to clear.
- **Ruin Card Interaction:** If *Ruin* is drawn, **all player gold on hand AND all pending transfers in escrow are destroyed**. The total combined loss is logged and tracked in `ruin_history` so it can be restored if reversed by *Fates*.

### Death & "Die & Resurrect" Button
- Tactical action costing **1,000 gp** for spell components (deducted from Player Gold first, then Party Gold).
- **Insufficient Funds:** If combined wealth is `< 1,000 gp`, death is permanent; **Game Over**.
- **Temple Failsafe:** If *Temple* is active, the bound deity performs a free resurrection instead of charging 1,000 gp.
- **Effects Stripped on Death:**
  - Devil enmity (*Flames*) is cleared.
  - *Sun* temporary HP buff is removed (accumulated magic item loot remains).
  - Active *Fates* charges are **permanently lost**.

---

## 5. Time Progression & Daily Ambushes

Advancing time (via **"Advance 1 Day"**, *Beast* transformation, *Maze*, *Corpse*, *Fey*, or *Jester*) triggers:
1. **Heroic Inspiration Reset:** Restores Heroic Inspiration (Human trait).
2. **Escrow Progression:** Decrements transfer countdowns; deposits completed transfers into Party Wealth.
3. **1-Year Expirations:** Clears cards that expire after 365 days (*Tomb*, *Map*, *Sage*).
4. **Beast Form Countdown:** Decrements animal form duration.
5. **Daily Ambush Checks:**
   - **Flames:** `active_flames * 5%` chance of lethal devil strike each day.
   - **Rogues:** If `active_rogues > 3`, `(active_rogues - 3) * 5%` chance of assassination.
   - **Undead:** If `active_undead > 10`, `(active_undead - 10) * 5%` chance of revenant army assault.

---

## 6. The Card Draw Pipeline & Interactive Modal

### Phase State Machine
```
[DRAW CARD] 
    │
    ├── Has Heroic Inspiration? 
    │     ├── YES ──► modal_phase = "d100_wait" (15s timer; click dice to reroll; click card to reveal)
    │     └── NO  ──► modal_phase = "revealed"  (0.5s spin anim, locks immediately)
    │
    ▼
[REVEALED SCREEN]
    ├── Top: D100 dice (locked) + Card preview (name & emoji)
    ├── Middle: Light yellow box (Description) + Large text (Result Text)
    ├── Secondary Dice: Rolled in-place (0.5s spin anim; rerollable if inspiration was not spent)
    ├── Choice Dropdowns: Filtered dynamically (Balance, Elemental, Throne, Puzzle, Star)
    └── Continue Button: ALWAYS present. Disabled during 0.5s spin; clickable as soon as dice lock.
```

### Heroic Inspiration Rules
- **Usage:** Clicking a d10 or secondary die spends Heroic Inspiration.
- **Single-Use Lock:** Once spent, the die rerolls (0.5s animation), the 15-second timer terminates immediately, and the card proceeds to lock in.
- **Rerolling into Rerolls (67–100):** If a reroll lands on 67–100 on the 66-card table, it resolves as **🎲 Roll again**, allowing you to continue and automatically chain into the next card.

---

## 7. Card Stacking & Override Rules Reference

| Card | Category | Stacking / Resolution Behavior |
| :--- | :--- | :--- |
| **Aberration** | Buff | `can_stack: false`. Does not duplicate. |
| **Balance** | Choice | `can_stack: true`. +2 to one stat, -2 to another (min 5, max 22), or Skip. |
| **Beast** | Condition | `can_stack: false`. Locks character into beast form for `2d12` days; advances time. |
| **Bridge** | Buff | **Overrides if higher.** Time Stop charges = `max(current, roll)`. |
| **Door** | Buff | **Overrides if higher.** Gate charges = `max(current, roll)`. |
| **Moon** | Buff | **Overrides if higher.** Wish charges = `max(current, roll)`. Decrements by 1 on use; deleted at 0. |
| **Elemental** | Buff | Single card entry. Choice dropdown dynamically filters out already-obtained immunities. |
| **Throne** | Buff | Single card entry. Choice dropdown dynamically filters out already-obtained expertise skills. |
| **Well** | Buff | Single card entry. Details increment: `+3 Cantrips` ➔ `+6` ➔ `+9` ➔ `+12` ➔ caps at `+13 Cantrips`. |
| **Sun** | Loot + Buff | Grants stacking magic item in `loot`; non-stacking `+10 Temp HP` in `buffs` (cleared on death). |
| **Shield** | Buff | `can_stack: false`. AC becomes 12 + DEX. Does not duplicate. |
| **Temple** | Buff | `can_stack: true`. Each draw adds a bound deity charge for free resurrection or divine intervention. |
| **Tomb / Sage** | Buff | `can_stack: false`. Drawing again resets expiration day to `day_count + 365`. |
| **Fiend** | Flavor | Passive interaction; does not add an enemy. |
| **Fool** | Draw Chain | 72 hours disadvantage (advances 3 days). Clicking Continue automatically chains the next card draw. |
| **Roll again** | Draw Chain | 67–100 on 66-card table. Clicking Continue automatically chains the next card draw. |
| **Star** | Choice | Dropdown choice to increase any attribute by +2 (max 24). |
| **Tower** | Phase | Rolls 4d10 (2 cards) with live previews. 15s reroll window. Select 1 card to keep and resolve. |

---

## 8. Purification & Undo Mechanics

### 1. Wish Cleansing & Wish Stress (`🌀`)
- Can remove active curses, enemies, or *Beast Form*.
- Each use consumes 1 Wish from *Moon* (buff is removed when count hits 0).
- **Conditional 33% Stress Check:** Checked **only if `causes_wish_stress: true`** in `deck.json` for that target. If true, a 33% roll applies `Wish Stress` (`🌀`), permanently preventing future Wish casting. If false, the check is skipped.

### 2. Temple Divine Intervention
- Can only cleanse targets that have **`divine_intervention_removal: true`** in `deck.json`. The Temple button is disabled for all other targets.

### 3. Fates Reality Manipulation
- **Reversing Wish Stress:**
  - Using *Fates* on `Wish Stress` cures the stress, **restores +1 Wish charge to Moon**, and **re-applies whatever burden the Wish originally erased** (e.g., re-draining the exact Wisdom lost to *Puzzle*, or re-wiping gold restored from *Ruin*).
- **Reversing Puzzle:** Restores the exact stat and amount drained during the most recent pull.
- **Reversing Ruin:** Restores all personal gold on hand and all pending transfers lost during that ruin event.
- **Game-Over Intervention:** If a card draw triggers Game Over (*Donjon*, *Void*, *Talons*, lethal *Skull*, age death, or 0 INT) and *Fates* is active, an emergency button appears: **"🪡 Expend Fates to Erase Card"**, rewinding the catastrophe.

---

## 9. UI & Formatting Specifications

1. **Floating Global Tooltip:** Tooltips are anchored to the document root (`position: fixed`) and follow cursor position. They **never get clipped** by overflow scrolling or box boundaries.
2. **Emoji-Only Status Display:** Inventory and Status items show solely the emoji icon with an `xN` badge beneath it if count > 1. All text captions are hidden.
3. **Tooltip Contents:** Hovering over any status item reveals its `short_description`, expiration day, and subtext (e.g., proficient skills, elemental immunities, or `+X Cantrips`).
4. **Heroic Inspiration Indicator:** A prominent status card on the sidebar indicates **READY TO REROLL** or **EXHAUSTED**.
5. **Game Log:** Formatted as an icon ribbon with the **newest events inserted at the front** (leftmost).