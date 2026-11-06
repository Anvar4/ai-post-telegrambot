from app.content.limits import validate_poll, validate_quiz

OK_OPTS = ["Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z"]


def test_quiz_valid() -> None:
    assert validate_quiz("Qaysi tugma nusxa oladi?", OK_OPTS, 0, "Ctrl+C — nusxa olish.") == []


def test_quiz_question_too_long() -> None:
    assert validate_quiz("a" * 301, OK_OPTS, 0, "x")
    assert validate_quiz("a" * 300, OK_OPTS, 0, "x") == []


def test_quiz_needs_four_options() -> None:
    assert validate_quiz("Savol?", OK_OPTS[:3], 0, "x")
    assert validate_quiz("Savol?", [*OK_OPTS, "Ctrl+A"], 0, "x")


def test_quiz_correct_index_in_range() -> None:
    assert validate_quiz("Savol?", OK_OPTS, 4, "x")
    assert validate_quiz("Savol?", OK_OPTS, -1, "x")


def test_quiz_option_and_explanation_limits() -> None:
    assert validate_quiz("Savol?", ["a" * 101, "b", "c", "d"], 0, "x")
    assert validate_quiz("Savol?", OK_OPTS, 0, "e" * 201)
    assert validate_quiz("Savol?", OK_OPTS, 0, "e" * 200) == []


def test_quiz_duplicate_or_empty_options() -> None:
    assert validate_quiz("Savol?", ["a", "a", "b", "c"], 0, "x")
    assert validate_quiz("Savol?", ["a", " ", "b", "c"], 0, "x")


def test_poll_limits() -> None:
    assert validate_poll("Qaysi brauzer?", ["Chrome", "Firefox"]) == []
    assert validate_poll("Qaysi brauzer?", ["Chrome"])
    assert validate_poll("Qaysi brauzer?", [f"v{i}" for i in range(13)])
    assert validate_poll("Qaysi brauzer?", [f"v{i}" for i in range(12)]) == []
    assert validate_poll("", ["a", "b"])
