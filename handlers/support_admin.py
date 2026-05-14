from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from handlers import main_menu


router = Router()


@router.callback_query(lambda c: c.data == "support:ticket_solved")
async def support_ticket_solved_badge(callback: types.CallbackQuery):
    await main_menu.support_ticket_solved_badge(callback)


@router.callback_query(lambda c: c.data and c.data.startswith("support:reply_ticket:"))
async def support_owner_reply_open(callback: types.CallbackQuery, state: FSMContext):
    await main_menu.support_owner_reply_open(callback, state)


@router.message(main_menu.SupportOwnerReplyFlow.waiting_message)
async def support_owner_reply_router(message: types.Message, state: FSMContext):
    await main_menu.support_owner_reply_router(message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("support:solve_ticket:"))
async def support_ticket_solve(callback: types.CallbackQuery):
    await main_menu.support_ticket_solve(callback)
