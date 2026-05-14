from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from handlers import custom_services, main_menu, owner_requests, reseller_recharge


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


@router.callback_query(lambda c: c.data and c.data.startswith("owner_rchg:accept:"))
async def owner_accept_reseller_topup(callback: types.CallbackQuery):
    await reseller_recharge.owner_accept_reseller_topup(callback)


@router.callback_query(lambda c: c.data and c.data.startswith("owner_rchg:reject:"))
async def owner_reject_reseller_topup(callback: types.CallbackQuery):
    await reseller_recharge.owner_reject_reseller_topup(callback)


@router.callback_query(lambda c: c.data and c.data.startswith("owner_rchg:manual:"))
async def owner_manual_reseller_topup_start(callback: types.CallbackQuery, state: FSMContext):
    await reseller_recharge.owner_manual_reseller_topup_start(callback, state)


@router.message(reseller_recharge.OwnerResellerTopupFSM.waiting_manual_amount)
async def owner_manual_reseller_topup_apply(message: types.Message, state: FSMContext):
    await reseller_recharge.owner_manual_reseller_topup_apply(message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("verify_owner:"))
async def owner_review_callback(callback: types.CallbackQuery):
    await owner_requests.owner_review_callback(callback)


@router.callback_query(lambda c: c.data and (c.data.startswith("cstm:preorders:") or c.data == "custom_preorder:list"))
async def show_pending_custom_preorders(callback: types.CallbackQuery, state: FSMContext):
    await custom_services.show_pending_custom_preorders(callback, state)


@router.callback_query(lambda c: c.data and c.data.startswith("custom_preorder:view:"))
async def view_custom_preorder(callback: types.CallbackQuery):
    await custom_services.view_custom_preorder(callback)


@router.callback_query(lambda c: c.data and c.data.startswith("custom_preorder:fulfill:"))
async def fulfill_custom_preorder(callback: types.CallbackQuery):
    await custom_services.fulfill_custom_preorder(callback)


@router.callback_query(lambda c: c.data and c.data.startswith("custom_preorder:reject:"))
async def reject_custom_preorder(callback: types.CallbackQuery):
    await custom_services.reject_custom_preorder(callback)
