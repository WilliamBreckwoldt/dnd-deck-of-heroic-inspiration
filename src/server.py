# src/server.py
from fastapi import FastAPI, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import random
import uuid
from .models import GameState
from .economy import die_and_resurrect, queue_gold_transfer
from .deck_manager import DECK_DATA, get_valid_d100, get_card_for_roll, roll_secondary, SECONDARY_DICE_MAP
from .game_engine import advance_time, commit_card_final, consume_charge

app = FastAPI()

# Store independent game states per player session
SESSIONS: dict[str, GameState] = {}

def get_or_create_session(session_id: str | None) -> tuple[str, GameState]:
    """Retrieves an existing game state or spawns a fresh session for a player."""
    if not session_id or session_id not in SESSIONS:
        new_id = session_id or str(uuid.uuid4())
        SESSIONS[new_id] = GameState(deck_size=66)
        return new_id, SESSIONS[new_id]
    return session_id, SESSIONS[session_id]

class ActionPayload(BaseModel):
    action: str
    data: dict = {}

@app.get("/api/state")
def get_state(x_session_id: str | None = Header(default=None)): 
    session_id, st = get_or_create_session(x_session_id)
    return {"session_id": session_id, "state": st.model_dump()}

@app.get("/api/deck")
def get_deck(): 
    return DECK_DATA

def setup_secondary_and_choices(st: GameState):
    c_name = st.pending_card["name"]
    if c_name in SECONDARY_DICE_MAP:
        st.secondary_dice_types = SECONDARY_DICE_MAP[c_name]
        st.secondary_rolls = roll_secondary(st.secondary_dice_types)
    else:
        st.secondary_dice_types = []
        st.secondary_rolls = []

    if c_name == "Balance": st.pending_choice_type = "balance"
    elif c_name == "Elemental": st.pending_choice_type = "elemental"
    elif c_name == "Puzzle": st.pending_choice_type = "puzzle"
    elif c_name == "Throne": st.pending_choice_type = "throne"
    elif c_name == "Star": st.pending_choice_type = "star"
    elif c_name == "Tower": st.pending_choice_type = "tower"
    else: st.pending_choice_type = None

@app.post("/api/action")
def handle_action(payload: ActionPayload, x_session_id: str | None = Header(default=None)):
    session_id, st = get_or_create_session(x_session_id)

    if payload.action == "new_game": 
        SESSIONS[session_id] = GameState(deck_size=payload.data.get("size", 66))
        st = SESSIONS[session_id]
    
    elif payload.action == "draw": 
        st.current_roll = get_valid_d100(st.deck_size, st.depleted_cards)
        st.pending_card = get_card_for_roll(DECK_DATA, st.current_roll, st.deck_size, st.depleted_cards)
        setup_secondary_and_choices(st)
        st.modal_phase = "d100_wait" if st.has_heroic_inspiration else "revealed"

    elif payload.action == "reroll_d100":
        if st.has_heroic_inspiration:
            st.has_heroic_inspiration = False
            die = payload.data["die"]
            if die == "tens": st.current_roll.tens = random.randint(0, 9)
            else: st.current_roll.units = random.randint(0, 9)
            
            st.pending_card = get_card_for_roll(DECK_DATA, st.current_roll, st.deck_size, st.depleted_cards)
            setup_secondary_and_choices(st)
            st.modal_phase = "revealed"

    elif payload.action == "reveal_d100":
        st.modal_phase = "revealed"

    elif payload.action == "reroll_sec":
        if st.has_heroic_inspiration:
            st.has_heroic_inspiration = False
            idx = payload.data["idx"]
            st.secondary_rolls[idx] = random.randint(1, st.secondary_dice_types[idx])

    elif payload.action == "continue":
        c_name = st.pending_card["name"]
        if c_name == "Tower":
            st.log_event("🗼", "Tower drawn: Rolling two cards to choose between.")
            r1 = get_valid_d100(st.deck_size, st.depleted_cards, avoid_names=["Tower", "Roll again"])
            r2 = get_valid_d100(st.deck_size, st.depleted_cards, avoid_names=["Tower", "Roll again", get_card_for_roll(DECK_DATA, r1, st.deck_size, st.depleted_cards)["name"]])
            st.tower_rolls = [r1, r2]
            st.tower_cards = [get_card_for_roll(DECK_DATA, r1, st.deck_size, st.depleted_cards), get_card_for_roll(DECK_DATA, r2, st.deck_size, st.depleted_cards)]
            st.modal_phase = "tower_wait" if st.has_heroic_inspiration else "tower_choices"
        elif c_name in ["Roll again", "Fool"]:
            commit_card_final(st, payload.data)
            st.current_roll = get_valid_d100(st.deck_size, st.depleted_cards)
            st.pending_card = get_card_for_roll(DECK_DATA, st.current_roll, st.deck_size, st.depleted_cards)
            setup_secondary_and_choices(st)
            st.modal_phase = "d100_wait" if st.has_heroic_inspiration else "revealed"
            return {"session_id": session_id, "state": st.model_dump()}
        else:
            commit_card_final(st, payload.data)
            st.modal_phase = "idle"
            st.pending_card = None

    elif payload.action == "fates_save":
        if "Fates" in st.buffs:
            del st.buffs["Fates"]
            st.game_over = False
            st.is_alive = True
            st.modal_phase = "idle"
            st.pending_card = None
            st.log_event("🪡", "Reality unraveled! Fates erased the disastrous card draw.")

    elif payload.action == "reroll_tower":
        if st.has_heroic_inspiration:
            st.has_heroic_inspiration = False
            c_idx = payload.data["card_idx"]
            die = payload.data["die"]
            avoid = ["Tower", "Roll again"]
            if c_idx == 0: avoid.append(st.tower_cards[1]["name"])
            else: avoid.append(st.tower_cards[0]["name"])
            
            while True:
                if die == "tens": st.tower_rolls[c_idx].tens = random.randint(0, 9)
                else: st.tower_rolls[c_idx].units = random.randint(0, 9)
                c = get_card_for_roll(DECK_DATA, st.tower_rolls[c_idx], st.deck_size, st.depleted_cards)
                if c["name"] not in avoid:
                    break
            
            st.tower_cards[c_idx] = get_card_for_roll(DECK_DATA, st.tower_rolls[c_idx], st.deck_size, st.depleted_cards)
            st.modal_phase = "tower_choices"

    elif payload.action == "reveal_tower":
        st.modal_phase = "tower_choices"

    elif payload.action == "choice_tower":
        st.pending_card = st.tower_cards[payload.data["idx"]]
        setup_secondary_and_choices(st)
        st.modal_phase = "revealed"

    elif payload.action == "rest": 
        advance_time(st, 1)
        st.log_event("⛺", "Regained Heroic Inspiration.")
    elif payload.action == "die": die_and_resurrect(st)
    elif payload.action == "transfer": queue_gold_transfer(st)
    elif payload.action == "purify": consume_charge(st, payload.data["source"], payload.data["target"])
    
    return {"session_id": session_id, "state": st.model_dump()}

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Deck of Many Things Simulator</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <style>
        body { background-color: #f3f4f6; font-family: sans-serif; }
        .hover-card {
            display: inline-flex; align-items: center; justify-content: center;
            border: 1px solid #d1d5db; border-radius: 8px; background: white; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.05); user-select: none;
            transition: transform 0.1s, border-color 0.1s;
        }
        .hover-card:hover { transform: scale(1.05); border-color: #3b82f6; }
        
        .dice-box {
            width: 80px; height: 80px; border: 4px solid #d1d5db; border-radius: 16px;
            font-size: 40px; font-weight: bold; display: flex; align-items: center; 
            justify-content: center; background: white; transition: transform 0.1s; user-select: none;
        }
        .dice-box.interactive { cursor: pointer; border-color: #3b82f6; color: #3b82f6; }
        .dice-box.interactive:hover { transform: scale(1.05); background: #eff6ff; }
        .dice-box.locked { border-color: #f59e0b; color: #f59e0b; cursor: default; }

        .card-box {
            width: 140px; height: 190px; border: 4px dashed #9ca3af; border-radius: 12px;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            background: white; padding: 10px; text-align: center; user-select: none; transition: transform 0.1s;
        }
        .card-box.interactive { cursor: pointer; border-color: #3b82f6; }
        .card-box.interactive:hover { transform: scale(1.05); box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2); }
    </style>
</head>
<body class="p-6">
    <div id="app" class="max-w-6xl mx-auto flex gap-6 relative">
        
        <!-- WELCOME / INTRO DIALOG -->
        <div v-if="showIntro" class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100000] p-4">
            <div class="bg-white rounded-2xl shadow-2xl p-6 max-w-lg w-full text-center border border-gray-200">
                <h2 class="text-2xl font-black text-gray-900 mb-3">Welcome, Adventurer!</h2>
                <p class="text-gray-700 leading-relaxed text-sm text-left mb-6 bg-gray-50 p-4 rounded-xl border border-gray-200">
                    You are a <strong>13th level Human Wizard</strong> with some downtime and a <strong>Deck of Many Things</strong> (technically the 66 card "Deck of Many More Things" but you can also select the 13 or 22 card Deck of Many Things variants when you start a new run).
                    <br/><br/>
                    As a 5.5e Human you gain <strong>Heroic Inspiration</strong> every long rest, and this allows you to <strong>manipulate any dice roll by clicking on the result.</strong> Considering the Deck of Many Things is a d100 roll (two d10 dice, you can re-roll one of them), perhaps you can manipulate the deck to your advantage...
                    <br/><br/>
                    How strong can you become?
                </p>
                <button @click="showIntro = false" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-6 rounded-xl shadow transition">
                    🧙 Draw some cards! 🃏
                </button>
            </div>
        </div>

        <!-- GLOBAL FLOATING TOOLTIP -->
        <div v-if="hoverTooltip.show" 
             :style="{ top: hoverTooltip.y + 'px', left: hoverTooltip.x + 'px' }" 
             class="fixed z-[99999] pointer-events-none -translate-x-1/2 -translate-y-full mb-2 bg-gray-900/95 text-white text-xs px-3 py-2 rounded-lg shadow-xl max-w-xs whitespace-pre-line border border-gray-700">
            {{ hoverTooltip.text }}
        </div>

        <!-- Left Panel: Stats -->
        <div class="w-1/3 bg-white p-4 rounded-xl shadow border">
            <h2 class="text-xl font-bold mb-3">Greg the Wizard</h2>
            
            <!-- Heroic Inspiration Indicator -->
            <div :class="s.has_heroic_inspiration ? 'bg-amber-50 border-amber-400 text-amber-900 shadow-sm' : 'bg-gray-50 border-gray-200 text-gray-400'"
                 class="p-3 rounded-xl border-2 text-center font-bold mb-4 flex items-center justify-center gap-3 transition">
                <span class="text-3xl">{{ s.has_heroic_inspiration ? '✨' : '⚪' }}</span>
                <div class="text-left">
                    <div class="text-xs uppercase tracking-wide opacity-75">Heroic Inspiration</div>
                    <div class="text-base font-black leading-tight">
                        {{ s.has_heroic_inspiration ? 'READY TO REROLL' : 'EXHAUSTED' }}
                    </div>
                </div>
            </div>

            <!-- Health & Vitals -->
            <div class="text-sm bg-gray-100 p-3 rounded mb-4">
                <b>HP:</b> {{ calculatedHP }}<span v-if="s.temp_hp > 0"> (+10)</span><br/>
                <b>Age:</b> {{ s.age }} yrs | <b>Height:</b> {{ formatHeight(s.height_inches) }}<br/>
                <b>Speeds:</b> Walk {{s.walking_speed}} | Climb {{s.climbing_speed}} | Fly {{s.flying_speed}}
            </div>

            <!-- Ability Scores -->
            <div class="text-sm bg-gray-100 p-3 rounded mb-4">
                <b>STR</b> {{s.strength}} | <b>DEX</b> {{s.dexterity}} | <b>CON</b> {{s.constitution}}<br/>
                <b>INT</b> {{s.intelligence}} | <b>WIS</b> {{s.wisdom}} | <b>CHA</b> {{s.charisma}}
            </div>

            <!-- Economy -->
            <div class="text-sm bg-gray-100 p-3 rounded mb-4">
                <b>Player GP:</b> {{ formatGold(s.player_gold) }}<br/>
                <b>Party GP:</b> {{ formatGold(s.party_gold) }} <span class="text-gray-500">(Pending: {{ formatGold(pendingGold) }})</span><br/>
                <b>Day:</b> {{s.day_count}}
            </div>

            <!-- Inventory / Curses / Buffs: EMOJI ONLY + COUNT -->
            <h2 class="text-xl font-bold mb-4 mt-6">🎒 Inventory & Statuses</h2>
            <div v-for="(dict, title) in trackedEntities" :key="title" class="mb-3">
                <div v-if="Object.keys(dict).length > 0">
                    <strong class="capitalize">{{title}}:</strong><br/>
                    <div class="flex flex-wrap gap-2 mt-1">
                        <div v-for="(item, key) in dict" 
                             class="hover-card flex flex-col items-center justify-center p-2 min-w-[48px] h-12 cursor-help relative"
                             @mouseenter="showTip($event, getEntityTooltip(item, key))" 
                             @mouseleave="hideTip">
                            <span class="text-2xl leading-none">{{ item.emoji }}</span>
                            <span v-if="item.count > 1" class="text-[11px] font-bold text-gray-600 leading-tight">x{{ item.count }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Right Panel: Actions -->
        <div class="w-2/3 flex flex-col gap-4">
            <div class="bg-white p-4 rounded-xl shadow border flex justify-between items-center">
                <div>
                    <label class="mr-2 font-bold">Deck Size:</label>
                    <select v-model="deckSize" class="border rounded p-1">
                        <option value="13">13</option><option value="22">22</option><option value="66">66</option>
                    </select>
                </div>
                <button @click="startNewGame" class="bg-gray-200 px-4 py-2 rounded font-bold hover:bg-gray-300">🔄 New Game</button>
            </div>

            <!-- Fatal Game Over Alert with Fates Safeguard -->
            <div v-if="s.game_over" class="bg-red-50 border-2 border-red-500 text-red-900 p-4 rounded-xl flex items-center justify-between">
                <div>
                    <h3 class="text-lg font-black">GAME OVER</h3>
                    <p>{{ s.game_over_reason }}</p>
                </div>
                <button v-if="hasFates" @click="api('fates_save')" class="bg-purple-600 text-white font-bold px-4 py-2 rounded-xl shadow hover:bg-purple-700 animate-pulse">
                    🪡 Use Fates to Erase Fate
                </button>
            </div>

            <button @click="drawCard" :disabled="s.game_over || s.active_beast_days > 0" class="w-full bg-blue-600 text-white text-2xl font-bold py-6 rounded-xl shadow hover:bg-blue-700 disabled:opacity-50 transition">
                Draw a card
            </button>

            <div class="bg-white p-4 rounded-xl shadow border flex flex-wrap gap-2">
                <button @click="api('rest')" :disabled="s.game_over" class="bg-indigo-100 text-indigo-800 px-4 py-2 rounded font-bold hover:bg-indigo-200">Take a Long Rest</button>
                <button @click="api('die')" :disabled="s.game_over" class="bg-red-100 text-red-800 px-4 py-2 rounded font-bold hover:bg-red-200">Die & Resurrect (1,000 gp)</button>
                <button @click="api('transfer')" :disabled="s.game_over" class="bg-green-100 text-green-800 px-4 py-2 rounded font-bold hover:bg-green-200">Transfer gold to party</button>
            </div>

            <!-- Purify Panel -->
            <div class="bg-white p-4 rounded-xl shadow border flex items-center gap-4">
                <select v-model="purifyTarget" class="border rounded p-2 flex-grow">
                    <option value="" disabled>Select Curse/Enemy to Cleanse...</option>
                    <option v-for="t in curableTargets" :value="t">{{t}}</option>
                </select>
                <button @click="api('purify', {source: 'Wish', target: purifyTarget})" :disabled="!canWish" class="bg-purple-600 text-white px-4 py-2 rounded font-bold hover:bg-purple-700 disabled:opacity-50">🌙 Wish</button>
                <button @click="api('purify', {source: 'Fates', target: purifyTarget})" :disabled="!canFates" class="bg-purple-600 text-white px-4 py-2 rounded font-bold hover:bg-purple-700 disabled:opacity-50">🪡 Fates</button>
                <button @click="api('purify', {source: 'Temple', target: purifyTarget})" :disabled="!canTemple" class="bg-purple-600 text-white px-4 py-2 rounded font-bold hover:bg-purple-700 disabled:opacity-50">🛕 Temple</button>
            </div>

            <!-- Game Log with Unclipped Tooltips -->
            <div class="bg-white p-4 rounded-xl shadow border h-64 overflow-y-auto">
                <h3 class="font-bold text-lg mb-2">📜 Game Log</h3>
                <div class="flex flex-wrap gap-2">
                    <div v-for="log in s.history_log" 
                         class="hover-card text-2xl w-11 h-11 cursor-help"
                         @mouseenter="showTip($event, log.text)" 
                         @mouseleave="hideTip">
                        {{ log.emoji }}
                    </div>
                </div>
            </div>
        </div>

        <!-- BLURRED OVERLAY MODAL -->
        <div v-if="s.modal_phase !== 'idle'" class="fixed inset-0 bg-black/60 backdrop-blur-md flex items-center justify-center z-50">
            <div class="bg-white border rounded-xl shadow-2xl p-6 w-full max-w-2xl text-center flex flex-col items-center">
                
                <h2 class="text-2xl font-bold mb-4 text-blue-600" v-if="s.modal_phase === 'd100_wait'">⏳ Resolving in {{timeLeft}}s</h2>
                <h2 class="text-2xl font-bold mb-4 text-purple-600" v-else-if="s.modal_phase === 'tower_wait'">⏳ Resolving in {{timeLeft}}s</h2>
                <h2 class="text-2xl font-bold mb-4 text-purple-600" v-else-if="s.modal_phase === 'tower_choices'">🗼 Choose Your Fate</h2>
                <h2 class="text-2xl font-bold mb-4 text-gray-700" v-else-if="s.modal_phase === 'revealed'">🎴 Card Outcome</h2>
                <h2 class="text-2xl font-bold mb-4 text-gray-400" v-else>Rolling...</h2>

                <!-- TOWER ROLLS (4 DICE) -->
                <div v-if="s.modal_phase.startsWith('tower')" class="flex flex-col items-center mb-6">
                    <div class="flex gap-8 justify-center">
                        <div v-for="(roll, idx) in [0, 1]" class="flex flex-col items-center">
                            <div class="flex gap-2 mb-4">
                                <div class="dice-box" :class="{'locked': !isAnimTower[idx].tens && s.modal_phase !== 'tower_wait', 'interactive': s.modal_phase === 'tower_wait' && s.has_heroic_inspiration}" @click="clickTowerDie(idx, 'tens')">
                                    {{ isAnimTower[idx].tens ? String(animTower[idx].tens).padStart(2,'0') : (s.tower_rolls[idx] ? String(s.tower_rolls[idx].tens*10).padStart(2,'0') : '00') }}
                                </div>
                                <div class="dice-box" :class="{'locked': !isAnimTower[idx].units && s.modal_phase !== 'tower_wait', 'interactive': s.modal_phase === 'tower_wait' && s.has_heroic_inspiration}" @click="clickTowerDie(idx, 'units')">
                                    {{ isAnimTower[idx].units ? animTower[idx].units : (s.tower_rolls[idx] ? s.tower_rolls[idx].units : '0') }}
                                </div>
                            </div>
                            <div class="card-box" :class="{'interactive': s.modal_phase === 'tower_wait' && !isAnimating}" @click="clickCard">
                                <div style="font-size: 55px;">{{ (isAnimTower[idx].tens || isAnimTower[idx].units) ? animTower[idx].emoji : (s.tower_cards[idx] ? s.tower_cards[idx].emoji : '❓') }}</div>
                                <div class="font-bold mt-2 leading-tight">{{ (isAnimTower[idx].tens || isAnimTower[idx].units) ? animTower[idx].name : (s.tower_cards[idx] ? s.tower_cards[idx].name : '...') }}</div>
                            </div>
                            <button v-if="s.modal_phase === 'tower_choices'" @click="api('choice_tower', {idx: idx})" class="mt-4 bg-blue-600 text-white px-4 py-2 rounded font-bold hover:bg-blue-700">Keep Card {{idx+1}}</button>
                        </div>
                    </div>
                    <!-- Tower click hint (Shows on first draw of the run) -->
                    <div v-if="s.modal_phase === 'tower_wait' && !hasShownCardHint" class="mt-4 text-sm font-bold text-blue-700 leading-snug bg-blue-50 px-5 py-2.5 rounded-xl border border-blue-200 shadow-sm animate-pulse">
                        Click the card to reveal immediately! 👆<br/>
                        <span class="text-xs text-blue-500 font-normal">(or click one of the dice to re-roll it)</span>
                    </div>
                </div>

                <!-- STANDARD D100 -->
                <div v-if="!s.modal_phase.startsWith('tower')" class="flex flex-col items-center mb-6">
                    <div class="flex gap-8 justify-center items-center">
                        <div class="flex gap-2">
                            <div class="dice-box" :class="{'locked': !isAnimTens && s.modal_phase !== 'd100_wait', 'interactive': s.modal_phase === 'd100_wait' && s.has_heroic_inspiration}" @click="clickDie('tens')">
                                {{ isAnimTens ? String(animD100.tens).padStart(2,'0') : (s.current_roll ? String(s.current_roll.tens*10).padStart(2,'0') : '00') }}
                            </div>
                            <div class="dice-box" :class="{'locked': !isAnimUnits && s.modal_phase !== 'd100_wait', 'interactive': s.modal_phase === 'd100_wait' && s.has_heroic_inspiration}" @click="clickDie('units')">
                                {{ isAnimUnits ? animD100.units : (s.current_roll ? s.current_roll.units : '0') }}
                            </div>
                        </div>
                        <div class="card-box" :class="{'interactive': (s.modal_phase === 'd100_wait' || (s.modal_phase === 'revealed' && s.pending_card && s.pending_card.name === 'Roll again')) && !isAnimating}" @click="clickCard">
                            <div style="font-size: 55px;">{{ (isAnimTens || isAnimUnits) ? animD100.emoji : (s.pending_card ? s.pending_card.emoji : '❓') }}</div>
                            <div class="font-bold mt-2 leading-tight">{{ (isAnimTens || isAnimUnits) ? animD100.name : (s.pending_card ? s.pending_card.name : '...') }}</div>
                        </div>
                    </div>
                    <!-- Standard card click hint (Shows on first draw of the run) -->
                    <div v-if="s.modal_phase === 'd100_wait' && !hasShownCardHint" class="mt-4 text-sm font-bold text-blue-700 leading-snug bg-blue-50 px-5 py-2.5 rounded-xl border border-blue-200 shadow-sm animate-pulse">
                        Click the card to {{ (s.pending_card && s.pending_card.name === 'Roll again') ? 're-roll' : 'reveal' }} immediately! 👆<br/>
                        <span class="text-xs text-blue-500 font-normal">(or click one of the dice to re-roll it)</span>
                    </div>
                </div>

                <!-- CARD REVEALED -->
                <div v-if="s.modal_phase === 'revealed' && s.pending_card" class="w-full">
                    
                    <div class="bg-yellow-100 text-yellow-900 p-3 rounded mb-4 text-sm text-left">
                        {{ s.pending_card.description }}
                    </div>
                    <div class="text-xl font-bold mb-4">
                        {{ s.pending_card.result_text }}
                    </div>

                    <!-- Secondary Dice -->
                    <div v-if="s.secondary_rolls && s.secondary_rolls.length > 0" class="flex gap-3 justify-center mb-6">
                        <div v-for="(roll, i) in s.secondary_rolls" class="dice-box text-2xl" 
                             :class="{
                                 'locked': !isAnimSec, 
                                 'interactive': !isAnimSec && s.has_heroic_inspiration
                             }" 
                             @click="clickSecDie(i)">
                            {{ (isAnimSec && (animSecTarget === null || animSecTarget === i)) ? animSec[i] : roll }}
                        </div>
                    </div>

                    <!-- Choices Dropdowns -->
                    <div v-if="s.pending_choice_type" class="mb-6 flex justify-center gap-4">
                        <!-- Balance -->
                        <div v-if="s.pending_choice_type === 'balance'" class="flex gap-2">
                            <select v-model="c1" class="border p-2 rounded"><option disabled value="">+2 Stat</option><option v-for="st in ['strength','dexterity','constitution','intelligence','wisdom','charisma','Skip']">{{st}}</option></select>
                            <select v-model="c2" class="border p-2 rounded"><option disabled value="">-2 Stat</option><option v-for="st in ['strength','dexterity','constitution','intelligence','wisdom','charisma','Skip']">{{st}}</option></select>
                        </div>
                        <!-- Elemental -->
                        <select v-if="s.pending_choice_type === 'elemental'" v-model="c1" class="border p-2 rounded">
                            <option disabled value="">Choose Immunity</option>
                            <option v-for="e in availableElementalChoices" :value="e">{{e}}</option>
                        </select>
                        <!-- Throne -->
                        <select v-if="s.pending_choice_type === 'throne'" v-model="c1" class="border p-2 rounded">
                            <option disabled value="">Choose Expertise</option>
                            <option v-for="sk in availableThroneChoices" :value="sk">{{sk}}</option>
                        </select>
                        <!-- Puzzle -->
                        <select v-if="s.pending_choice_type === 'puzzle'" v-model="c1" class="border p-2 rounded">
                            <option disabled value="">Stat to Drain</option>
                            <option value="intelligence">Intelligence</option>
                            <option value="wisdom">Wisdom</option>
                        </select>
                        <!-- Star -->
                        <select v-if="s.pending_choice_type === 'star'" v-model="c1" class="border p-2 rounded">
                            <option disabled value="">Select Ability Score to +2</option>
                            <option v-for="st in ['strength','dexterity','constitution','intelligence','wisdom','charisma']" :value="st">{{st.toUpperCase()}}</option>
                        </select>
                    </div>

                    <div v-if="wouldCardEndGame && hasFates" class="mb-4">
                        <button @click="api('fates_save')" class="bg-purple-600 text-white font-bold py-3 px-6 rounded-xl hover:bg-purple-700 animate-pulse">
                            🪡 Expend Fates to Erase Card
                        </button>
                    </div>

                    <button @click="submitContinue" 
                            :disabled="isAnimSec || isAnimTens || isAnimUnits || !canContinue" 
                            class="bg-blue-600 text-white font-bold py-3 px-8 rounded-xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition">
                        {{ (s.pending_card && s.pending_card.name === 'Roll again' && !s.has_heroic_inspiration) ? 'Rerolling... 🎲' : 'Continue' }}
                    </button>
                </div>

            </div>
        </div>

    </div>

    <script>
        const { createApp } = Vue;
        createApp({
            data() {
                return {
                    showIntro: true,
                    hasShownCardHint: false,
                    autoAdvanceTimer: null,
                    s: { history_log: [], buffs: {}, curses: {}, allies: {}, enemies: {}, loot: {}, pending_transfers: [], secondary_rolls: [], modal_phase: 'idle', age: 25, height_inches: 68 },
                    deckData: [], deckSize: "66", purifyTarget: "", c1: "", c2: "",
                    isAnimTens: false, isAnimUnits: false, isAnimSec: false, animSecTarget: null,
                    isAnimTower: [{tens: false, units: false}, {tens: false, units: false}],
                    animD100: {tens: 0, units: 0, name: "", emoji: ""},
                    animTower: [{tens: 0, units: 0, name: "", emoji: ""}, {tens: 0, units: 0, name: "", emoji: ""}],
                    animSec: [0,0,0], timerInt: null, timeLeft: 15, animInt: null,
                    hoverTooltip: { show: false, text: '', x: 0, y: 0 }
                }
            },
            computed: {
                trackedEntities() { return {buffs: this.s.buffs, curses: this.s.curses, allies: this.s.allies, enemies: this.s.enemies, loot: this.s.loot}; },
                pendingGold() { return this.s.pending_transfers.reduce((a, b) => a + b.amount, 0); },
                hasFates() { return !!this.s.buffs['Fates']; },
                calculatedHP() {
                    let conMod = Math.floor((this.s.constitution - 10) / 2);
                    return (conMod * 13) + 54 + this.s.max_hp_bonus;
                },
                availableElementalChoices() {
                    const all = ["Acid", "Cold", "Fire", "Lightning", "Thunder"];
                    const existing = this.s.buffs["Elemental"] ? this.s.buffs["Elemental"].details : [];
                    return all.filter(e => !existing.includes(e));
                },
                availableThroneChoices() {
                    const all = ["History", "Insight", "Intimidation", "Persuasion"];
                    const details = this.s.buffs["Throne"] ? this.s.buffs["Throne"].details : [];
                    return all.filter(sk => !details.includes(sk));
                },
                wouldCardEndGame() {
                    if(!this.s.pending_card) return false;
                    const lethalNames = ["Donjon", "Void", "Talons"];
                    return lethalNames.includes(this.s.pending_card.name);
                },
                curableTargets() {
                    let ts = this.s.active_beast_days > 0 ? ["Beast Form"] : [];
                    return ts.concat(Object.keys(this.s.curses)).concat(["Flames","Rogue","Undead"].filter(k => this.s.enemies[k]));
                },
                canWish() { 
                    return this.s.buffs['Moon'] && this.s.buffs['Moon'].count > 0 && !this.s.wish_stressed && this.purifyTarget && this.purifyTarget !== 'Wish Stress'; 
                },
                canFates() { 
                    return !!this.s.buffs['Fates'] && !!this.purifyTarget; 
                },
                canTemple() {
                    if(!this.s.buffs['Temple'] || !this.purifyTarget || this.purifyTarget === 'Wish Stress') return false;
                    if(this.purifyTarget === "Beast Form") {
                        let bc = this.deckData.find(c => c.name === "Beast");
                        return bc ? !!bc.divine_intervention_removal : false;
                    }
                    let item = this.s.curses[this.purifyTarget] || this.s.enemies[this.purifyTarget];
                    return item ? !!item.divine_intervention_removal : false;
                },
                isAnimating() { return this.isAnimTens || this.isAnimUnits || this.isAnimSec || this.isAnimTower[0].tens || this.isAnimTower[0].units || this.isAnimTower[1].tens || this.isAnimTower[1].units; },
                canContinue() {
                    let p = this.s.pending_choice_type;
                    if(!p || p === 'tower') return true;
                    if(p === 'balance') return (this.c1 && this.c2 && this.c1 !== this.c2) || this.c1 === 'Skip';
                    return !!this.c1;
                }
            },
            methods: {
                clearAutoAdvance() {
                    if (this.autoAdvanceTimer) {
                        clearTimeout(this.autoAdvanceTimer);
                        this.autoAdvanceTimer = null;
                    }
                },
                checkAutoAdvance() {
                    this.clearAutoAdvance();
                    if (this.isAnimating) return;
                    if (this.s.modal_phase === 'revealed' && this.s.pending_card && this.s.pending_card.name === 'Roll again') {
                        this.autoAdvanceTimer = setTimeout(() => {
                            if (this.s.modal_phase === 'revealed' && this.s.pending_card && this.s.pending_card.name === 'Roll again') {
                                this.submitContinue();
                            }
                        }, 1000);
                    }
                },
                getSessionId() {
                    let sid = localStorage.getItem('dnd_deck_session_id');
                    if (!sid) {
                        sid = 'user_' + Math.random().toString(36).substring(2, 9) + Date.now().toString(36);
                        localStorage.setItem('dnd_deck_session_id', sid);
                    }
                    return sid;
                },
                startNewGame() {
                    this.clearAutoAdvance();
                    this.hasShownCardHint = false;
                    this.api('new_game', {size: parseInt(this.deckSize)});
                },
                markHintShown() {
                    this.hasShownCardHint = true;
                },
                showTip(e, text) {
                    if (!text) return;
                    const rect = e.currentTarget.getBoundingClientRect();
                    this.hoverTooltip = {
                        show: true,
                        text: text,
                        x: rect.left + rect.width / 2,
                        y: rect.top - 6
                    };
                },
                hideTip() {
                    this.hoverTooltip.show = false;
                },
                getEntityTooltip(item, key) {
                    let tip = item.description || key;
                    if (item.details && item.details.length) {
                        tip += `\\n${item.details.join(', ')}`;
                    }
                    if (item.expiration_day) {
                        tip += `\\n(Expires Day ${item.expiration_day})`;
                    }
                    return tip;
                },
                formatGold(val) {
                    return Number(val || 0).toLocaleString('en-US') + ' gp';
                },
                formatHeight(inches) {
                    let ft = Math.floor(inches / 12);
                    let rem = inches % 12;
                    return `${ft}'${rem}" (${inches} in)`;
                },
                getCard(tens, units) {
                    let total = (tens * 10) + units;
                    if(total === 0) total = 100;
                    let k = this.deckSize + "_card_deck";
                    for(let c of this.deckData) {
                        if(this.s.depleted_cards.includes(c.name)) continue;
                        if(c.roll_ranges && c.roll_ranges[k] && total >= c.roll_ranges[k].min && total <= c.roll_ranges[k].max) return c;
                    }
                    return {name: "Roll again", emoji: "🎲"};
                },
                async api(action, data={}) {
                    try {
                        const res = await fetch('/api/action', { 
                            method: 'POST', 
                            headers: {
                                'Content-Type': 'application/json',
                                'X-Session-ID': this.getSessionId()
                            }, 
                            body: JSON.stringify({action, data}) 
                        });
                        const payload = await res.json();
                        this.s = payload.state;
                        if (!this.isAnimating) {
                            this.checkAutoAdvance();
                        }
                    } catch (err) { console.error(err); }
                },
                async init() {
                    const rDeck = await fetch('/api/deck'); 
                    this.deckData = await rDeck.json();
                    
                    const rState = await fetch('/api/state', {
                        headers: { 'X-Session-ID': this.getSessionId() }
                    });
                    const payload = await rState.json();
                    this.s = payload.state;
                },
                startTimer() {
                    clearInterval(this.timerInt); this.timeLeft = 15;
                    this.timerInt = setInterval(() => {
                        this.timeLeft--;
                        if(this.timeLeft <= 0) {
                            clearInterval(this.timerInt);
                            this.revealNow();
                        }
                    }, 1000);
                },
                async revealNow() {
                    this.markHintShown();
                    this.clearAutoAdvance();
                    clearInterval(this.timerInt);
                    if(this.s.modal_phase === 'd100_wait') {
                        await this.api('reveal_d100');
                        if(this.s.secondary_rolls && this.s.secondary_rolls.length > 0) {
                            this.runAnim('sec');
                        } else {
                            this.checkAutoAdvance();
                        }
                    } else if(this.s.modal_phase === 'tower_wait') {
                        await this.api('reveal_tower');
                    }
                },
                clickCard() {
                    if(this.isAnimating) return;
                    if(this.s.pending_card && this.s.pending_card.name === 'Roll again') {
                        this.markHintShown();
                        clearInterval(this.timerInt);
                        this.clearAutoAdvance();
                        this.submitContinue();
                        return;
                    }
                    if(!this.s.modal_phase.endsWith('_wait')) return;
                    this.revealNow();
                },
                runAnim(type, arg1=false, arg2=false, arg3=false, arg4=false) {
                    clearInterval(this.animInt); clearInterval(this.timerInt);
                    if(type === 'd100') { 
                        this.isAnimTens = arg1; 
                        this.isAnimUnits = arg2; 
                    } else if(type === 'sec') { 
                        this.isAnimSec = true; 
                        this.animSecTarget = (typeof arg1 === 'number') ? arg1 : null;
                    } else if(type === 'tower') { 
                        this.isAnimTower[0].tens = arg1; this.isAnimTower[0].units = arg2; 
                        this.isAnimTower[1].tens = arg3; this.isAnimTower[1].units = arg4; 
                    }
                    
                    this.animInt = setInterval(() => {
                        if(type === 'd100') {
                            let t = this.isAnimTens ? Math.floor(Math.random()*10) : (this.s.current_roll ? this.s.current_roll.tens : 0);
                            let u = this.isAnimUnits ? Math.floor(Math.random()*10) : (this.s.current_roll ? this.s.current_roll.units : 0);
                            this.animD100.tens = t; this.animD100.units = u;
                            let c = this.getCard(t, u); this.animD100.name = c.name; this.animD100.emoji = c.emoji || "❓";
                        } else if (type === 'sec') {
                            this.animSec = this.s.secondary_dice_types.map((sides, i) => {
                                if (this.animSecTarget === null || this.animSecTarget === i) {
                                    return Math.floor(Math.random() * sides) + 1;
                                } else {
                                    return this.s.secondary_rolls[i];
                                }
                            });
                        } else if (type === 'tower') {
                            for(let i of [0,1]) {
                                let t = this.isAnimTower[i].tens ? Math.floor(Math.random()*10) : (this.s.tower_rolls[i] ? this.s.tower_rolls[i].tens : 0);
                                let u = this.isAnimTower[i].units ? Math.floor(Math.random()*10) : (this.s.tower_rolls[i] ? this.s.tower_rolls[i].units : 0);
                                this.animTower[i].tens = t; this.animTower[i].units = u;
                                let c = this.getCard(t, u); this.animTower[i].name = c.name; this.animTower[i].emoji = c.emoji || "❓";
                            }
                        }
                    }, 50);

                    setTimeout(() => {
                        clearInterval(this.animInt);
                        this.isAnimTens = false; this.isAnimUnits = false; this.isAnimSec = false; this.animSecTarget = null;
                        this.isAnimTower = [{tens: false, units: false}, {tens: false, units: false}];
                        
                        if (type === 'd100' && this.s.secondary_rolls && this.s.secondary_rolls.length > 0 && this.s.modal_phase !== 'd100_wait') {
                            this.runAnim('sec');
                            return;
                        }

                        if(this.s.modal_phase.endsWith('_wait')) {
                            this.startTimer();
                        } else {
                            this.checkAutoAdvance();
                        }
                    }, 500);
                },
                async drawCard() {
                    this.clearAutoAdvance();
                    this.runAnim('d100', true, true);
                    await this.api('draw');
                },
                async clickDie(die) {
                    if(this.s.modal_phase !== 'd100_wait' || !this.s.has_heroic_inspiration || this.isAnimating) return;
                    this.markHintShown();
                    this.clearAutoAdvance();
                    clearInterval(this.timerInt);
                    this.runAnim('d100', die === 'tens', die === 'units');
                    await this.api('reroll_d100', {die});
                },
                async clickSecDie(idx) {
                    if(this.s.modal_phase !== 'revealed' || !this.s.has_heroic_inspiration || this.isAnimating) return;
                    clearInterval(this.timerInt);
                    this.runAnim('sec', idx);
                    await this.api('reroll_sec', {idx});
                },
                async clickTowerDie(cIdx, die) {
                    if(this.s.modal_phase !== 'tower_wait' || !this.has_heroic_inspiration || this.isAnimating) return;
                    this.markHintShown();
                    clearInterval(this.timerInt);
                    await this.api('reroll_tower', {card_idx: cIdx, die});
                    this.runAnim('tower', cIdx===0&&die==='tens', cIdx===0&&die==='units', cIdx===1&&die==='tens', cIdx===1&&die==='units');
                },
                async submitContinue() {
                    this.clearAutoAdvance();
                    let prevCard = this.s.pending_card ? this.s.pending_card.name : '';
                    await this.api('continue', {c1: this.c1, c2: this.c2});
                    this.c1 = ""; this.c2 = "";
                    if(this.s.modal_phase.startsWith('tower')) {
                        this.runAnim('tower', true, true, true, true);
                    } else if((prevCard === 'Roll again' || prevCard === 'Fool') && this.s.modal_phase !== 'idle') {
                        this.runAnim('d100', true, true);
                    }
                }
            },
            mounted() { this.init(); }
        }).mount('#app');
    </script>
</body>
</html>
"""

@app.get("/")
def index(): 
    return HTMLResponse(INDEX_HTML)