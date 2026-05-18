from aiogram.fsm.state import State, StatesGroup


class CardsSubmitFlow(StatesGroup):
    waiting_brand = State()
    waiting_brand_search = State()
    waiting_denomination = State()
    waiting_currency = State()
    waiting_region = State()
    waiting_code = State()
    waiting_pin = State()


class CardsWithdrawFlow(StatesGroup):
    waiting_amount = State()
    waiting_currency = State()
    waiting_destination = State()


class CardsAdminFlow(StatesGroup):
    waiting_pricing_rates = State()
    waiting_pricing_entry = State()
