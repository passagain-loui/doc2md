# test_cleaner.py

````python
from doc2md.core.cleaner import optimize, token_estimate


def test_compresses_spaces_but_not_in_code_fence():
    md = "a    b\t\tc\n```python\nx    =    1\n```\n"
    out = optimize(md)
    assert "a b c" in out
    assert "x    =    1" in out


def test_deduplicates_consecutive_lines():
    md = "Header\nHeader\nbody\nbody\n"
    out = optimize(md)
    assert out.count("Header") == 1
    assert out.count("body") == 1


def test_strips_style_script_and_css_blocks():
    md = "<style>.x{color:red}</style><script>evil()</script>\nText { font: bold }\nKeep"
    out = optimize(md)
    assert "color:red" not in out
    assert "evil" not in out
    assert "{ font" not in out
    assert "Keep" in out


def test_collapses_blank_runs():
    md = "a\n\n\n\n\nb"
    out = optimize(md)
    assert "\n\n\n" not in out


def test_zero_width_chars_removed():
    out = optimize("ok\u200b\ufeffay")
    assert out.strip() == "okay"


def test_unterminated_fence_is_preserved_verbatim():
    md = "intro\n```\na   b\n"
    out = optimize(md)
    assert "a   b" in out
    assert "intro a" not in out.replace("\n", " ").replace("intro ", "intro")


def test_token_estimate():
    assert token_estimate("") == 0
    assert token_estimate("x" * 401) == 100
````
