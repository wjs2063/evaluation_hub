from app.api.routes.evaluations import _evaluate_row, parse_dataset


def test_parse_csv_dataset() -> None:
    rows = parse_dataset(
        "sample.csv",
        b"input,actual_output,expected_output\nhello,world,world\n",
    )

    assert rows == [
        {"input": "hello", "actual_output": "world", "expected_output": "world"}
    ]


def test_exact_match_passes() -> None:
    result = _evaluate_row(
        {"input": "greeting", "actual_output": " Hello  world ", "expected_output": "hello world"},
        index=0,
        threshold=0.7,
    )

    assert result.passed is True
    assert result.score == 1
