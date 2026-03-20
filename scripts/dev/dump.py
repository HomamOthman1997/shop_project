import os
import ast
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "project_dump.txt")

# مجلدات/أنماط يجب استبعادها تماماً
EXCLUDE_DIRS = {
    "__pycache__", ".git", ".idea", ".vscode",
    "venv", ".venv", "env", "node_modules",
    "site-packages", "dist", "build", "pip-wheel-metadata",
    ".eggs", ".pytest_cache"
}

# امتدادات نصية نسمح بضمها (باقي الامتدادات الثنائية نتجاهلها)
TEXT_EXTENSIONS = {
    ".py", ".json", ".md", ".txt", ".yml", ".yaml", ".ini", ".cfg",
    ".env", ".sql", ".csv", ".html", ".htm", ".css", ".js", ".ts",
    ".jsx", ".tsx", ".toml", ".rst", ".lock", ".properties", ".xml",
    ".bat", ".sh", ".ps1", ".dockerfile", "Dockerfile", ".cfg"
}

# امتدادات ثنائية نتجاهلها
BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".zip", ".tar", ".gz", ".whl", ".db", ".sqlite",
    ".mp4", ".mp3", ".mov", ".avi", ".pdf"
}

# حد حجم الملف (بايت) لتجنب ملفات ضخمة عن طريق الخطأ (مثلاً 5 ميغا)
MAX_FILE_SIZE = 5 * 1024 * 1024


def remove_comments_and_docstrings(source: str) -> str:
    try:
        parsed = ast.parse(source)
        for node in ast.walk(parsed):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    node.body.pop(0)
        cleaned_code = ast.unparse(parsed)
        lines = [line for line in cleaned_code.splitlines() if line.strip()]
        return "\n".join(lines)
    except Exception:
        lines = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                code_part = line.split('#')[0].rstrip()
                if code_part:
                    lines.append(code_part)
        return "\n".join(lines)


def safe_read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception as e:
            return f"# [SKIPPED] error reading file: {e}"


def is_text_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    if ext in BINARY_EXTENSIONS:
        return False
    # افتراضياً: إذا الحجم صغير ونهاية الملف قابلة للقراءة كنص، نسمح به
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_SIZE:
            return False
        with open(path, "rb") as f:
            chunk = f.read(4096)
            # إذا وجد بايت صفري أو بايت غير نصي بكثرة، اعتبره ثنائي
            if b'\x00' in chunk:
                return False
            # محاولة فك الترميز كـ utf-8
            try:
                chunk.decode("utf-8")
                return True
            except Exception:
                return False
    except Exception:
        return False


def collect_all_project_files(base_path: str):
    output_lines = []
    files_collected = 0

    for folder, dirs, files in os.walk(base_path, topdown=True):
        # استبعد مجلدات محددة
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        # استبعد المجلد الناتج عن نفس السكربت (output) إن وُجد
        if OUTPUT_FILE and os.path.commonpath([os.path.abspath(folder), os.path.abspath(OUTPUT_FILE)]) == os.path.abspath(folder):
            continue

        for file in sorted(files):
            path = os.path.join(folder, file)

            # لا نضم ملف الإخراج نفسه
            if os.path.abspath(path) == os.path.abspath(OUTPUT_FILE):
                continue

            # تحقق من الامتداد والحجم ونوع الملف
            _, ext = os.path.splitext(file)
            ext = ext.lower()

            if ext in BINARY_EXTENSIONS:
                continue

            if not is_text_file(path):
                continue

            # اقرأ الملف بأمان
            source = safe_read_file(path)
            if source.startswith("# [SKIPPED]"):
                continue

            # إذا كان JSON اتركه كما هو، وإلا نظف ملفات بايثون من التعليقات والدوسكسترنغ
            if ext == ".py":
                cleaned = remove_comments_and_docstrings(source)
            else:
                cleaned = "\n".join([line for line in source.splitlines() if line.strip()])

            if not cleaned.strip():
                continue

            output_lines.append(f"\n===== FILE: {path} =====")
            output_lines.extend(cleaned.splitlines())
            files_collected += 1

    # اكتب كل المحتوى في ملف واحد
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
        f.write("\n\n===== END OF DUMP =====\n")
        f.write(f"Total files: {files_collected}\n")

    print(f"Done! {files_collected} files saved into {OUTPUT_FILE}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dump project files into a single file (excluding env/libs).")
    args = parser.parse_args()
    collect_all_project_files(BASE_DIR)
