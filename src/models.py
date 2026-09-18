# src/models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class D100Roll(BaseModel):
    tens: int
    units: int
    @property
    def total(self) -> int:
        val = (self.tens * 10) + self.units
        return 100 if val == 0 else val

class TrackedEntity(BaseModel):
    name: str
    emoji: str
    description: str
    count: int = 1
    details: List[str] = Field(default_factory=list)
    expiration_day: Optional[int] = None
    causes_wish_stress: bool = False
    divine_intervention_removal: bool = False

class GameState(BaseModel):
    deck_size: int = 66
    is_alive: bool = True
    game_over: bool = False
    game_over_reason: str = ""
    cards_drawn_count: int = 0
    history_log: List[Dict[str, str]] = Field(default_factory=list)

    # Character Stats & Attributes
    strength: int = 8
    dexterity: int = 14
    constitution: int = 14
    intelligence: int = 17
    wisdom: int = 12
    charisma: int = 10
    walking_speed: int = 30
    climbing_speed: int = 0
    flying_speed: int = 0
    max_hp_bonus: int = 0
    temp_hp: int = 0

    # Physical Traits
    age: int = 35
    height_inches: int = 68

    # Economy
    player_gold: int = 5000
    party_gold: int = 15000
    pending_transfers: List[Dict[str, int]] = Field(default_factory=list)

    # Time & Resources
    day_count: int = 1
    has_heroic_inspiration: bool = True
    active_beast_days: int = 0
    wish_stressed: bool = False

    # Tracked Dictionaries
    buffs: Dict[str, TrackedEntity] = Field(default_factory=dict)
    curses: Dict[str, TrackedEntity] = Field(default_factory=dict)
    allies: Dict[str, TrackedEntity] = Field(default_factory=dict)
    enemies: Dict[str, TrackedEntity] = Field(default_factory=dict)
    loot: Dict[str, TrackedEntity] = Field(default_factory=dict)

    # Undo Histories
    puzzle_history: List[Dict[str, Any]] = Field(default_factory=list)
    ruin_history: List[Dict[str, Any]] = Field(default_factory=list)
    wish_removal_history: List[Dict[str, Any]] = Field(default_factory=list)

    modal_phase: str = "idle" 
    current_roll: Optional[D100Roll] = None
    pending_card: Optional[dict] = None
    
    secondary_dice_types: List[int] = Field(default_factory=list)
    secondary_rolls: List[int] = Field(default_factory=list)
    
    tower_rolls: List[D100Roll] = Field(default_factory=list)
    tower_cards: List[dict] = Field(default_factory=list)
    
    depleted_cards: List[str] = Field(default_factory=list)
    pending_choice_type: Optional[str] = None
    must_draw_again: bool = False

    def add_tracked(self, category: str, card: dict, specific_name: str = None, duration: int = None, details: str = None):
        name = specific_name or card["name"]
        emoji = card.get("emoji", "❓")
        desc = card.get("short_description") or card.get("description", "")
        wish_stress = card.get("causes_wish_stress", False)
        divine_removal = card.get("divine_intervention_removal", False)
        
        target_dict = getattr(self, category)
        if name in target_dict:
            target_dict[name].count += 1
            if details and details not in target_dict[name].details:
                target_dict[name].details.append(details)
        else:
            exp = self.day_count + duration if duration else None
            det = [details] if details else []
            target_dict[name] = TrackedEntity(
                name=name, 
                emoji=emoji, 
                description=desc, 
                count=1, 
                expiration_day=exp, 
                details=det,
                causes_wish_stress=wish_stress,
                divine_intervention_removal=divine_removal
            )

    def remove_tracked(self, category: str, name: str):
        target_dict = getattr(self, category)
        if name in target_dict:
            target_dict[name].count -= 1
            if target_dict[name].count <= 0:
                del target_dict[name]

    def log_event(self, emoji: str, text: str):
        safe_text = text.replace('"', '&quot;')
        self.history_log.insert(0, {"emoji": emoji, "text": safe_text})