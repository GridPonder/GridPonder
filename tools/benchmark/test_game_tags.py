from __future__ import annotations

from game_tags import validate_game_tags


def test_valid_tags_are_preserved_in_order() -> None:
    assert validate_game_tags(
        {"tags": ["routing", "spatial-planning"]},
        pack_id="game",
    ) == ("routing", "spatial-planning")


def test_invalid_duplicate_and_unknown_tags_fail() -> None:
    cases = [
        ({"tags": ["Not Normalized"]}, None),
        ({"tags": ["routing", "routing"]}, None),
        ({"tags": ["routing"]}, {"coverage"}),
    ]
    for manifest, allowed in cases:
        try:
            validate_game_tags(
                manifest,
                pack_id="game",
                allowed_tags=allowed,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid tags should fail: {manifest}")


def test_required_tags_fail_when_empty() -> None:
    try:
        validate_game_tags({}, pack_id="game", required=True)
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("required tags should fail when absent")


if __name__ == "__main__":
    test_valid_tags_are_preserved_in_order()
    test_invalid_duplicate_and_unknown_tags_fail()
    test_required_tags_fail_when_empty()
    print("3 passed")
