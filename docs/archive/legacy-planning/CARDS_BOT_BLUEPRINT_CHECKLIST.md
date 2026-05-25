# Cards Bot Blueprint Checklist

هذا الملف يربط بين متطلبات `PROJECT_BLUEPRINT.md` في مشروع `CyberZone-CardEX-main` وبين التنفيذ الحالي داخل:

- `C:\Users\CyberZone\PycharmProjects\shop_project`

الهدف:

- إبقاء بوت البطاقات مستقلًا كبوت خاص به
- لكن داخل نفس منطق ومعمارية مشروعنا الحالي
- مع معرفة ما اكتمل وما ما زال ناقصًا بوضوح

## 1) القرار المعماري

- [x] البوت مستقل كـ Telegram bot منفصل
- [x] التشغيل داخل نفس `bot_manager.py`
- [x] Dispatcher مستقل لبوت البطاقات
- [x] بقاء قاعدة البيانات مشتركة مع مشروعنا الحالي
- [ ] فصل routing من البوت المركزي إليه عبر زر Hub واضح
- [ ] إضافة username/token النهائيين في `.env`

## 2) نطاق MVP الذي سنلتزم به

اعتمادًا على الـ blueprint، MVP عندنا لبوت البطاقات هو:

- [x] User onboarding بسيط عبر `/start`
- [x] إنشاء user/wallet تلقائيًا
- [x] Card submission wizard
- [x] Wallet view
- [x] My cards
- [x] Withdrawal request flow
- [x] Owner review commands for cards
- [x] Owner review commands for withdrawals
- [x] Pending release scheduler
- [ ] Notifications للقبول/الرفض/الإتاحة
- [ ] Audit logs للحساسيات
- [ ] FX management
- [ ] Trader batching / trader statement
- [ ] Verification / trust / hold policies

## 3) طبقة البيانات

### implemented

- [x] `cardex_users`
- [x] `cardex_wallets`
- [x] `cardex_cards`
- [x] `cardex_pricing_rules`
- [x] `cardex_missing_pricing`
- [x] `cardex_withdrawals`
- [x] `cardex_ledger`
- [x] Mongo indexes bootstrap

### deferred

- [ ] `card_status_history`
- [ ] `wallet_release_schedules` collection مستقلة
- [ ] `exchange_rates`
- [ ] `withdrawal_proofs`
- [ ] `traders`
- [ ] `trader_batches`
- [ ] `trader_batch_cards`
- [ ] `trader_ledger_entries`
- [ ] `trader_payments`
- [ ] `audit_logs`
- [ ] `user_verification_profiles`
- [ ] `user_verification_files`
- [ ] `user_risk_flags`
- [ ] `hold_policies`
- [ ] `user_hold_policy_history`

## 4) User Flows

### onboarding

- [x] `/start`
- [x] user bootstrap
- [ ] terms + language within cards bot UX
- [ ] phone share request
- [ ] show SYP estimate if FX gets enabled

### card submission

- [x] choose brand
- [x] choose denomination
- [x] choose currency
- [x] choose region
- [x] code + optional pin
- [x] confirm + submit
- [x] missing pricing queue if no active pricing rule
- [ ] estimated value before final confirm from explicit pricing display
- [ ] add-another-card loop

### withdrawals

- [x] enter amount
- [x] choose payout currency
- [x] submit request
- [ ] USD/SYP detailed disclaimer
- [ ] payout proof upload lifecycle

## 5) Owner/Admin Workflows

### implemented

- [x] cards review queue
- [x] accept card
- [x] reject card
- [x] withdrawals queue
- [x] approve withdrawal
- [x] reject withdrawal
- [x] mark withdrawal paid
- [x] create pricing rule
- [x] missing pricing review list

### missing

- [ ] explicit `under_review` stage management
- [ ] rejection reason mandatory enforcement
- [ ] trader batching workflow
- [ ] trader payment recording
- [ ] FX activation workflow
- [ ] verification review workflow
- [ ] trust/hold assignment workflow
- [ ] admin topic routing inside owner group

## 6) Ledger Rules

### implemented

- [x] pending credit on card accept
- [x] pending -> available release
- [x] withdrawal request lock
- [x] withdrawal rejected release
- [x] withdrawal paid unlock
- [x] append-only style cardex ledger collection
- [x] wallet invariants block negative wallet buckets

### missing

- [ ] idempotency keys on owner actions
- [ ] invariant audit command
- [ ] dedicated release schedule records per card
- [ ] immutable audit trail around manual fixes

## 7) State Machines

### current practical state coverage

- [x] card: `submitted`
- [x] card: `customer_pending_credit`
- [x] card: `customer_available_credit`
- [x] card: `rejected`
- [x] withdrawal: `requested`
- [x] withdrawal: `approved`
- [x] withdrawal: `rejected`
- [x] withdrawal: `paid`

### missing to align with blueprint

- [ ] card: `under_review`
- [ ] card: `accepted`
- [ ] card: `batched_for_trader`
- [ ] card: `sent_to_trader`
- [ ] withdrawal: `under_review`
- [ ] withdrawal: `cancelled`
- [ ] verification machine
- [ ] machine validation tests against transitions

## 8) Notifications

- [ ] notify seller on card accepted
- [ ] notify seller on card rejected
- [ ] notify seller when pending becomes available
- [ ] notify seller on withdrawal approved
- [ ] notify seller on withdrawal rejected
- [ ] notify seller on withdrawal paid

## 9) RBAC / Compliance

- [x] owner-only commands for sensitive actions
- [ ] operator/admin roles beyond owner
- [ ] role matrix implementation
- [ ] audit logs for sensitive actions
- [ ] blacklist/watchlist flags
- [ ] verification gate for payout policy

## 10) Runtime / Jobs

- [x] cards bot dispatcher inside `bot_manager.py`
- [x] card release sweep job
- [ ] proof retention cleanup
- [ ] audit retention / cleanup
- [ ] notifications worker abstraction

## 11) What We Should Build Next

الأولوية التالية لبناء نسخة قوية من الـ MVP:

1. [ ] ربط بوت البطاقات بزر واضح من البوت المركزي
2. [ ] تنبيهات تلقائية للمستخدم عند قبول/رفض/إتاحة البطاقة
3. [ ] إضافة `card_status_history`
4. [ ] إضافة `under_review` بشكل صريح
5. [ ] فرض سبب رفض إلزامي
6. [ ] إضافة `exchange_rates` وSYP estimate
7. [ ] إضافة `withdrawal_proofs`
8. [ ] إضافة `audit_logs`

## 12) Files In Current Project

الملفات الأساسية الحالية:

- `C:\Users\CyberZone\PycharmProjects\shop_project\database\cardex_repo.py`
- `C:\Users\CyberZone\PycharmProjects\shop_project\services\cards_bot\service.py`
- `C:\Users\CyberZone\PycharmProjects\shop_project\services\cards_bot\states.py`
- `C:\Users\CyberZone\PycharmProjects\shop_project\services\cards_bot\keyboards.py`
- `C:\Users\CyberZone\PycharmProjects\shop_project\services\cards_bot\handlers.py`
- `C:\Users\CyberZone\PycharmProjects\shop_project\bot_manager.py`
- `C:\Users\CyberZone\PycharmProjects\shop_project\handlers\start.py`
- `C:\Users\CyberZone\PycharmProjects\shop_project\utils\bot_menu_context.py`

## 13) Scope Decision

لن ننقل هذه الأشياء كما هي من مشروع `CardEX` الخارجي:

- PostgreSQL migrations
- FastAPI admin API
- python-telegram-bot runtime

سنأخذ منها فقط:

- domain decisions
- state model
- workflow ordering
- ledger rules
- RBAC ideas

ثم نعيد تنفيذها داخل:

- `aiogram`
- `Mongo`
- `bot_manager.py`

