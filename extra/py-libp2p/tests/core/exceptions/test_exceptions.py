from libp2p.exceptions import (
    MultiError,
)


def test_multierror_str_and_storage():
    errors = [
        ValueError("bad value"),
        KeyError("missing key"),
        RuntimeError("custom error"),
    ]
    multi_error = MultiError(errors)
    # Check for storage
    assert multi_error.errors == errors
    # Check for representation
    expected = "Error 1: bad value\nError 2: 'missing key'\nError 3: custom error"
    assert str(multi_error) == expected
