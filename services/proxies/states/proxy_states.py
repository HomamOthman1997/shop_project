from aiogram.fsm.state import State, StatesGroup


class ProxyFlow(StatesGroup):
    menu = State()
    offers = State()

