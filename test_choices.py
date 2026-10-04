"""Right-wink choices: raw line stays until the user picks a change."""

from main import TextEngine


class _Words:
    def predict(self, prefix, n=3):
        if prefix == "hel":
            return ["hello", "help", "held"]
        return []


def _engine() -> TextEngine:
    return TextEngine(_Words(), typer=type("T", (), {"enabled": False, "type_text": lambda *a: None})())


def test_correction_is_offered_and_not_applied():
    engine = _engine()
    engine.current_word = "helo"
    assert engine.display_text().strip() == "helo"
    assert engine.choice_options() == [("raw", "helo"), ("clean", "HELLO")]
    engine.apply_choice(engine.choice_options(), 0)
    assert engine.display_text().strip() == "helo"


def test_choosing_clean_replaces_the_line():
    engine = _engine()
    engine.current_word = "helo"
    engine.apply_choice(engine.choice_options(), 1)
    assert engine.display_text().strip() == "HELLO"
    assert engine.choice_options() == []


def test_raw_line_is_first_and_two_suggestions_follow():
    engine = _engine()
    engine.current_word = "hel"
    assert engine.choice_options() == [
        ("raw", "hel"),
        ("word", "hello"),
        ("word", "help"),
    ]


def test_correction_and_suggestions_stay_within_three():
    engine = _engine()
    engine.text = "helo "
    engine.current_word = "hel"
    options = engine.choice_options()
    assert options == [
        ("raw", "helo hel"),
        ("clean", "HELLO HEL"),
        ("word", "hello"),
    ]


def test_choosing_a_suggestion_replaces_the_word():
    engine = _engine()
    engine.text = "you "
    engine.current_word = "hel"
    engine.apply_choice(engine.choice_options(), 1)
    assert engine.display_text().strip() == "you hello"


if __name__ == "__main__":
    test_correction_is_offered_and_not_applied()
    test_choosing_clean_replaces_the_line()
    test_raw_line_is_first_and_two_suggestions_follow()
    test_correction_and_suggestions_stay_within_three()
    test_choosing_a_suggestion_replaces_the_word()
    print("choice tests passed")
