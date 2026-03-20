# states/core_numbers_states.py
from aiogram.fsm.state import StatesGroup, State

class NumberFlow(StatesGroup):
    num_type = State()
    rental_home = State()
    country = State()
    state = State()
    service = State()
    rental_providers = State()
    rental_tv_duration = State()
    rental_tv_renew = State()
    rental_tv_state_choice = State()
    fetch_prices = State()
    confirm_buy = State()
    rental_options = State()
    rental_confirm = State()
    search_country = State()
    search_state = State()
