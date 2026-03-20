# handlers/inline_query_handlers.py

from aiogram import Router
from aiogram import types
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from services.numbers.service_map import SERVICE_MAP

router = Router()

# -----------------------------
# داتا الدول (مبدئياً – فيك تنقلها لملف مستقل لاحقاً)
# -----------------------------
COUNTRIES = [
    ("United States", "US", ["us", "usa", "united states", "america"]),
    ("United Kingdom", "UK", ["uk", "u k", "england", "britain", "united kingdom"]),
    ("Germany", "DE", ["de", "ger", "germany", "deutschland"]),
    ("France", "FR", ["fr", "fra", "france"]),
    ("Canada", "CA", ["ca", "can", "canada"]),
    ("India", "IN", ["in", "ind", "india", "bharat"]),
    ("Brazil", "BR", ["br", "bra", "brazil"]),
    ("Turkey", "TR", ["tr", "tur", "turkey", "turkiye"]),
    ("Saudi Arabia", "SA", ["sa", "ksa", "saudi", "saudi arabia"]),
    ("United Arab Emirates", "AE", ["ae", "uae", "emirates", "dubai"]),
]


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _smart_match(query: str, candidates: list[str]) -> bool:
    """
    تطابق بسيط وذكي:
    - يحذف المسافات الزايدة
    - يحوّل لحروف صغيرة
    - يدعم الاحتواء الجزئي
    """
    q = _normalize(query)
    for c in candidates:
        c_norm = _normalize(c)
        if q in c_norm or c_norm in q:
            return True
    return False


# -----------------------------
# Inline Query للدول
# query متوقعة مثل:
#   "country us"
#   "country united"
# -----------------------------
@router.inline_query()
async def inline_query_router(inline_query: InlineQuery):
    q = inline_query.query or ""
    q_norm = _normalize(q)

    # ما في شي → لا ترجع نتائج
    if not q_norm:
        await inline_query.answer([], cache_time=1)
        return

    # -------------------------
    # 1) بحث عن دولة
    # -------------------------
    if q_norm.startswith("country"):
        search_term = q_norm.replace("country", "", 1).strip()
        if not search_term:
            await inline_query.answer([], cache_time=1)
            return

        results: list[InlineQueryResultArticle] = []

        for name, code, aliases in COUNTRIES:
            candidates = [name, code] + aliases
            if _smart_match(search_term, candidates):
                # رسالة تظهر في الشات بعد الاختيار
                msg_text = f"✅ تم اختيار الدولة: {name} ({code})"

                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="متابعة اختيار الدولة",
                                callback_data=f"num_country_{code}"
                            )
                        ]
                    ]
                )

                results.append(
                    InlineQueryResultArticle(
                        id=f"country_{code}",
                        title=name,
                        description=f"اختيار الدولة: {name}",
                        input_message_content=InputTextMessageContent(
                            message_text=msg_text
                        ),
                        reply_markup=kb
                    )
                )

        await inline_query.answer(results, cache_time=1)
        return

    # -------------------------
    # 2) بحث عن خدمة
    # query متوقعة مثل:
    #   "service ipsos"
    #   "service tik"
    # -------------------------
    if q_norm.startswith("service"):
        search_term = q_norm.replace("service", "", 1).strip()
        if not search_term:
            await inline_query.answer([], cache_time=1)
            return

        results: list[InlineQueryResultArticle] = []

        # نفترض أن SERVICE_MAP هي مثل:
        # {
        #   "ipsos": {"display_name": "IPSOS", ...},
        #   "tiktok": {"display_name": "TikTok", ...},
        #   ...
        # }
        for internal_name, data in SERVICE_MAP.items():
            display_name = data.get("display_name", internal_name)
            aliases = data.get("aliases", [])

            candidates = [display_name, internal_name] + aliases

            if _smart_match(search_term, candidates):
                msg_text = f"✅ تم اختيار الخدمة: {display_name}"

                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="متابعة اختيار الخدمة",
                                callback_data=f"num_service_{internal_name}"
                            )
                        ]
                    ]
                )

                results.append(
                    InlineQueryResultArticle(
                        id=f"service_{internal_name}",
                        title=display_name,
                        description="اختيار الخدمة",
                        input_message_content=InputTextMessageContent(
                            message_text=msg_text
                        ),
                        reply_markup=kb
                    )
                )

        await inline_query.answer(results, cache_time=1)
        return

    # لو ما كان لا country ولا service → تجاهل
    await inline_query.answer([], cache_time=1)
