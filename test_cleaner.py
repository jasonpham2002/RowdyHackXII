"""SymSpell preview tests. No camera required."""

from cleaner import clean_message


def test_jammed_words_are_split():
    assert clean_message("youhavagoodnight") == "YOU HAVE GOODNIGHT"


def test_existing_spaces_stay_put():
    assert clean_message("please help") == "PLEASE HELP"
    assert clean_message("you have a good night") == "YOU HAVE A GOOD NIGHT"


def test_typo_inside_a_jammed_phrase():
    assert clean_message("youhvveagoodnight") == "YOU HAVE GOODNIGHT"
    assert "HELPING" not in clean_message("pleasehelpiminroom")


def test_short_acronyms_stay():
    assert clean_message("sos") == "SOS"
    assert clean_message("nasa") == "NASA"
    assert clean_message("fbi") == "FBI"
    assert clean_message("xyzq") == "XYZQ"


def test_mild_typos_are_corrected():
    assert clean_message("helo") == "HELLO"
    assert clean_message("nightt") == "NIGHT"


def test_empty_stays_empty():
    assert clean_message("") == ""
    assert clean_message("   ") == ""


if __name__ == "__main__":
    test_jammed_words_are_split()
    test_existing_spaces_stay_put()
    test_typo_inside_a_jammed_phrase()
    test_short_acronyms_stay()
    test_mild_typos_are_corrected()
    test_empty_stays_empty()
    print("cleaner tests passed")
