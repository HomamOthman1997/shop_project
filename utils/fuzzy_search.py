from rapidfuzz import fuzz, process

def fuzzy_find(query: str, choices: list, limit: int = 10, threshold: int = 40):
    """
    بحث ذكي:
    - يصحح الأخطاء
    - يتجاهل المسافات
    - يدعم الاختصارات
    - يرجع أفضل النتائج
    """

    query = query.strip().lower()

    results = process.extract(
        query,
        choices,
        scorer=fuzz.WRatio,
        limit=limit
    )

    # فلترة النتائج الضعيفة
    return [item for item, score, _ in results if score >= threshold]
