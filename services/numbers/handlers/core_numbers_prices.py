from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from services.numbers.keyboards.core_numbers_kb import provider_choice_kb
from services.numbers.manager import get_all_prices
from services.numbers.states.core_numbers_states import NumberFlow
from utils.translations import t

router = Router()


@router.message()
async def fetch_prices_handler(message: types.Message, state: FSMContext):
    """Legacy fallback handler for the fetch-prices state.

    Core flow currently uses callback handlers in `core_numbers.py`, but this
    message handler is kept safe/compatible in case a flow lands here.
    """
    current_state = await state.get_state()
    if current_state != NumberFlow.fetch_prices:
        return

    data = await state.get_data()
    lang = data.get("lang", "en")
    service = data.get("service")
    country = data.get("country")
    state_code = data.get("state")
    usd_to_syp_rate = float(data.get("usd_to_syp_rate") or 0)

    await message.answer(t(lang, "loading_prices"))

    prices = await get_all_prices(service, country, state_code)
    if not prices:
        return await message.answer(t(lang, "no_prices_available"))

    await message.answer(
        t(lang, "choose_provider_prompt"),
        reply_markup=provider_choice_kb(prices, lang=lang, usd_to_syp=usd_to_syp_rate),
    )
