from datetime import UTC, datetime, timedelta
import logging

from pymongo import ReturnDocument

from database.financial_ledger import credit_reseller_main_wallet, credit_user_wallet
from database.mongo import db

logger = logging.getLogger("recharge_repo")


ACTIVE_RECHARGE_STATUSES = ["pending", "processing", "need_more_proof"]


def _log_recharge_event(event: str, level: int = logging.INFO, **fields) -> None:
    payload = ", ".join(f"{key}={fields[key]!r}" for key in sorted(fields))
    logger.log(level, "recharge_event=%s%s", event, f" | {payload}" if payload else "")


def _wallet_kind(req: dict) -> str:
    return str(req.get("wallet_type") or "user").strip().lower()


async def bootstrap_recharge_indexes() -> None:
    await db.recharge_requests.create_index([("reseller_id", 1), ("status", 1), ("created_at", -1)], background=True)
    await db.recharge_requests.create_index([("user_id", 1), ("status", 1), ("created_at", -1)], background=True)
    await db.recharge_requests.create_index([("status", 1), ("reviewed_at", 1)], background=True)
    await db.recharge_requests.create_index([("status", 1), ("processing_started_at", 1)], background=True)


async def _ledger_applied_for_request(request_id, req: dict) -> bool:
    wallet_type = _wallet_kind(req)
    base = {
        "order_id": request_id,
        "reason": "recharge_request_accepted",
        "direction": "credit",
    }

    if wallet_type in {"reseller_main", "main", "reseller"}:
        reseller_id = int(req.get("reseller_id") or 0)
        if reseller_id <= 0:
            return False
        q = {
            **base,
            "owner_type": "reseller",
            "owner_id": reseller_id,
            "wallet_type": "reseller_main",
        }
    else:
        reseller_id = int(req.get("reseller_id") or 0)
        user_id = int(req.get("user_id") or 0)
        if reseller_id <= 0 or user_id <= 0:
            return False
        q = {
            **base,
            "owner_type": "user",
            "owner_id": user_id,
            "reseller_id": reseller_id,
            "wallet_type": "user",
        }

    found = await db.ledger_entries.find_one(q, {"_id": 1})
    return bool(found)


async def create_recharge_request(user_id, method, amount, proof_file_id, reseller_id, details=None, wallet_type="user"):
    now = datetime.now(UTC)
    amount = float(amount)
    reseller_id = int(reseller_id)

    existing = await db.recharge_requests.find_one_and_update(
        {
            "user_id": int(user_id),
            "reseller_id": reseller_id,
            "wallet_type": wallet_type,
            "status": {"$in": ACTIVE_RECHARGE_STATUSES},
        },
        {
            "$set": {
                "method": method,
                "amount": amount,
                "proof_file_id": proof_file_id,
                "wallet_type": wallet_type,
                "details": details or {},
                "status": "pending",
                "decision": None,
                "decision_note": None,
                "approved_amount": None,
                "reviewed_at": None,
                "reviewed_by": None,
                "proof_deleted_at": None,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if existing:
        existing["_reused"] = True
        _log_recharge_event(
            "request_reused",
            request_id=existing.get("_id"),
            user_id=int(user_id),
            reseller_id=reseller_id,
            wallet_type=wallet_type,
            amount=amount,
        )
        return existing

    req = {
        "user_id": int(user_id),
        "method": method,
        "amount": amount,
        "proof_file_id": proof_file_id,
        "reseller_id": reseller_id,
        "wallet_type": wallet_type,
        "details": details or {},
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "reviewed_at": None,
        "reviewed_by": None,
        "decision": None,
        "decision_note": None,
        "approved_amount": None,
        "proof_deleted_at": None,
    }
    res = await db.recharge_requests.insert_one(req)
    req["_id"] = res.inserted_id
    req["_reused"] = False
    _log_recharge_event(
        "request_created",
        request_id=req["_id"],
        user_id=int(user_id),
        reseller_id=reseller_id,
        wallet_type=wallet_type,
        amount=amount,
    )
    return req


async def get_recharge_requests_for_reseller(reseller_id, status="pending"):
    return await db.recharge_requests.find({"reseller_id": int(reseller_id), "status": status}).to_list(None)


async def update_recharge_request(
    request_id,
    status,
    reviewed_by,
    decision_note=None,
    approved_amount: float | None = None,
    expected_reseller_id: int | None = None,
):
    requested_approved_amount = float(approved_amount) if approved_amount is not None else None
    base_match = {"_id": request_id, "status": "pending"}
    if expected_reseller_id is not None:
        base_match["reseller_id"] = int(expected_reseller_id)

    if status != "accepted":
        updated = await db.recharge_requests.find_one_and_update(
            base_match,
            {
                "$set": {
                    "status": status,
                    "reviewed_at": datetime.now(UTC),
                    "reviewed_by": reviewed_by,
                    "decision": status,
                    "decision_note": decision_note,
                    "approved_amount": requested_approved_amount,
                    "updated_at": datetime.now(UTC),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated:
            _log_recharge_event(
                "request_decided",
                request_id=request_id,
                status=status,
                reviewed_by=reviewed_by,
                reseller_id=updated.get("reseller_id"),
                wallet_type=_wallet_kind(updated),
            )
        return updated

    # Only one worker may claim acceptance at a time.
    # Allow retry from failed, but never re-claim an already-processing request.
    accept_match = {"_id": request_id, "status": {"$in": ["pending", "failed"]}}
    if expected_reseller_id is not None:
        accept_match["reseller_id"] = int(expected_reseller_id)

    req = await db.recharge_requests.find_one_and_update(
        accept_match,
        {
            "$set": {
                "status": "processing",
                "reviewed_at": datetime.now(UTC),
                "reviewed_by": reviewed_by,
                "decision_note": decision_note,
                "approved_amount": requested_approved_amount,
                "decision": "accepted",
                "processing_started_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.BEFORE,
    )
    if not req:
        existing = await db.recharge_requests.find_one({"_id": request_id})
        if not existing:
            return None
        if existing.get("status") == "accepted":
            _log_recharge_event(
                "request_already_accepted",
                request_id=request_id,
                reviewed_by=reviewed_by,
                reseller_id=existing.get("reseller_id"),
                wallet_type=_wallet_kind(existing),
            )
            return existing
        if existing.get("status") == "processing":
            try:
                if await _ledger_applied_for_request(request_id, existing):
                    amount_done = float(
                        existing.get("approved_amount")
                        or requested_approved_amount
                        or existing.get("amount")
                        or 0
                    )
                    await db.recharge_requests.update_one(
                        {"_id": request_id, "status": "processing"},
                        {
                            "$set": {
                                "status": "accepted",
                                "approved_amount": amount_done,
                                "reviewed_at": existing.get("reviewed_at") or datetime.now(UTC),
                                "updated_at": datetime.now(UTC),
                            }
                        },
                    )
                    _log_recharge_event(
                        "request_processing_finalized_from_ledger",
                        request_id=request_id,
                        approved_amount=amount_done,
                        reviewed_by=reviewed_by,
                    )
                    return await db.recharge_requests.find_one({"_id": request_id})
            except Exception as exc:
                logger.exception("failed to finalize processing recharge id=%s: %s", request_id, exc)
            return existing
        return None

    amount = float(requested_approved_amount if requested_approved_amount is not None else (req.get("amount") or 0))
    if amount <= 0:
        await db.recharge_requests.update_one(
            {"_id": request_id, "status": "processing"},
            {"$set": {"status": "failed", "decision_note": "approved_amount_invalid", "updated_at": datetime.now(UTC)}},
        )
        _log_recharge_event(
            "request_failed_invalid_amount",
            level=logging.WARNING,
            request_id=request_id,
            reviewed_by=reviewed_by,
            approved_amount=amount,
        )
        return await db.recharge_requests.find_one({"_id": request_id})

    wallet_type = _wallet_kind(req)
    try:
        ledger_already_applied = await _ledger_applied_for_request(request_id, req)
        if ledger_already_applied:
            amount = float(req.get("approved_amount") or requested_approved_amount or req.get("amount") or amount)
            _log_recharge_event(
                "request_credit_already_applied",
                request_id=request_id,
                reviewed_by=reviewed_by,
                wallet_type=wallet_type,
                approved_amount=amount,
            )
        else:
            if wallet_type in {"reseller_main", "main", "reseller"}:
                reseller_id = int(req.get("reseller_id") or reviewed_by)
                await credit_reseller_main_wallet(
                    reseller_id=reseller_id,
                    amount=amount,
                    reason="recharge_request_accepted",
                    actor_id=int(reviewed_by),
                    order_id=request_id,
                )
            else:
                reseller_id = req.get("reseller_id")
                if reseller_id is None:
                    await db.recharge_requests.update_one(
                        {"_id": request_id, "status": "processing"},
                        {"$set": {"status": "failed", "decision_note": "missing_reseller_id", "updated_at": datetime.now(UTC)}},
                    )
                    _log_recharge_event(
                        "request_failed_missing_reseller",
                        level=logging.ERROR,
                        request_id=request_id,
                        reviewed_by=reviewed_by,
                        wallet_type=wallet_type,
                    )
                    return await db.recharge_requests.find_one({"_id": request_id})
                await credit_user_wallet(
                    user_id=int(req["user_id"]),
                    reseller_id=int(reseller_id),
                    amount=amount,
                    reason="recharge_request_accepted",
                    actor_id=int(reviewed_by),
                    order_id=request_id,
                )
            _log_recharge_event(
                "request_credit_applied",
                request_id=request_id,
                reviewed_by=reviewed_by,
                reseller_id=req.get("reseller_id"),
                user_id=req.get("user_id"),
                wallet_type=wallet_type,
                approved_amount=amount,
            )
    except Exception as exc:
        logger.exception("failed to apply accepted recharge request id=%s: %s", request_id, exc)
        try:
            if await _ledger_applied_for_request(request_id, req):
                amount_done = float(req.get("approved_amount") or requested_approved_amount or req.get("amount") or amount)
                await db.recharge_requests.update_one(
                    {"_id": request_id, "status": "processing"},
                    {
                        "$set": {
                            "status": "accepted",
                            "approved_amount": amount_done,
                            "reviewed_at": datetime.now(UTC),
                            "reviewed_by": reviewed_by,
                            "decision_note": "accepted_idempotent_recovery",
                            "updated_at": datetime.now(UTC),
                        }
                    },
                )
                _log_recharge_event(
                    "request_recovered_after_credit_error",
                    level=logging.WARNING,
                    request_id=request_id,
                    reviewed_by=reviewed_by,
                    approved_amount=amount_done,
                    wallet_type=wallet_type,
                )
                return await db.recharge_requests.find_one({"_id": request_id})
        except Exception as recover_exc:
            logger.exception("failed idempotent recovery for recharge id=%s: %s", request_id, recover_exc)
        await db.recharge_requests.update_one(
            {"_id": request_id, "status": "processing"},
            {
                "$set": {
                    "status": "failed",
                    "decision_note": f"ledger_apply_failed: {exc}",
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        _log_recharge_event(
            "request_failed_credit_apply",
            level=logging.ERROR,
            request_id=request_id,
            reviewed_by=reviewed_by,
            wallet_type=wallet_type,
            error=str(exc),
        )
        return await db.recharge_requests.find_one({"_id": request_id})

    try:
        await db.recharge_requests.update_one(
            {"_id": request_id, "status": "processing"},
            {
                "$set": {
                    "status": "accepted",
                    "approved_amount": amount,
                    "reviewed_at": datetime.now(UTC),
                    "reviewed_by": reviewed_by,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
    except Exception as exc:
        logger.exception(
            "accepted recharge finalized with delayed status update id=%s: %s",
            request_id,
            exc,
        )
        await db.recharge_requests.update_one(
            {"_id": request_id},
            {"$set": {"decision_note": f"status_finalize_pending: {exc}", "updated_at": datetime.now(UTC)}},
        )

    updated = await db.recharge_requests.find_one({"_id": request_id})
    if updated:
        _log_recharge_event(
            "request_accepted",
            request_id=request_id,
            reviewed_by=reviewed_by,
            reseller_id=updated.get("reseller_id"),
            user_id=updated.get("user_id"),
            wallet_type=_wallet_kind(updated),
            approved_amount=updated.get("approved_amount"),
        )
    return updated


async def recover_stuck_processing_recharges(*, max_age_minutes: int = 15, limit: int = 200) -> dict:
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    stuck = await db.recharge_requests.find(
        {
            "status": "processing",
            "processing_started_at": {"$lte": cutoff},
        }
    ).limit(limit).to_list(length=limit)

    stats = {"scanned": len(stuck), "recovered": 0, "requeued": 0}
    now = datetime.now(UTC)

    for req in stuck:
        req_id = req.get("_id")
        if not req_id:
            continue

        try:
            ledger_done = await _ledger_applied_for_request(req_id, req)
            if ledger_done:
                amount = float(req.get("approved_amount") or req.get("amount") or 0)
                await db.recharge_requests.update_one(
                    {"_id": req_id, "status": "processing"},
                    {
                        "$set": {
                            "status": "accepted",
                            "approved_amount": amount,
                            "decision_note": "auto_recovered_from_processing",
                            "reviewed_at": req.get("reviewed_at") or now,
                            "updated_at": now,
                        }
                    },
                )
                stats["recovered"] += 1
                _log_recharge_event(
                    "stuck_request_recovered",
                    level=logging.WARNING,
                    request_id=req_id,
                    approved_amount=amount,
                )
            else:
                await db.recharge_requests.update_one(
                    {"_id": req_id, "status": "processing"},
                    {
                        "$set": {
                            "status": "pending",
                            "decision": None,
                            "decision_note": "auto_requeued_from_processing_timeout",
                            "processing_started_at": None,
                            "updated_at": now,
                        }
                    },
                )
                stats["requeued"] += 1
                _log_recharge_event(
                    "stuck_request_requeued",
                    level=logging.WARNING,
                    request_id=req_id,
                )
        except Exception as exc:
            logger.exception("failed to recover stuck recharge id=%s: %s", req_id, exc)

    return stats


async def purge_accepted_recharge_proofs(*, keep_hours: int = 6, limit: int = 500) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=keep_hours)
    cursor = db.recharge_requests.find(
        {
            "status": "accepted",
            "proof_file_id": {"$exists": True, "$ne": None},
            "reviewed_at": {"$lte": cutoff},
            "$or": [
                {"proof_deleted_at": {"$exists": False}},
                {"proof_deleted_at": None},
            ],
        },
        {"_id": 1},
    ).limit(limit)

    ids = [doc["_id"] async for doc in cursor]
    if not ids:
        return 0

    now = datetime.now(UTC)
    res = await db.recharge_requests.update_many(
        {"_id": {"$in": ids}},
        {"$set": {"proof_file_id": None, "proof_deleted_at": now, "updated_at": now}},
    )
    purged = int(res.modified_count or 0)
    if purged:
        _log_recharge_event(
            "proofs_purged",
            keep_hours=keep_hours,
            purged=purged,
        )
    return purged

