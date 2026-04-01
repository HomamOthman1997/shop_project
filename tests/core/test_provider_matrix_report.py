from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.provider_matrix_report as provider_matrix_report


def test_provider_matrix_render_contains_runtime_tables() -> None:
    content = provider_matrix_report.render_markdown()
    assert "# Runtime Provider Matrix" in content
    assert "## Numbers providers" in content
    assert "## Proxy providers" in content
    assert "| smspool |" in content
    assert "## Proxy providers" in content


def test_provider_matrix_file_is_current() -> None:
    output_path = Path("docs/providers/runtime_provider_matrix.md")
    expected = provider_matrix_report.render_markdown()
    actual = output_path.read_text(encoding="utf-8")
    assert actual == expected
