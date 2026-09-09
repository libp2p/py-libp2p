"""
Basic unit tests for mDNS utils module.
"""

import string

from libp2p.discovery.mdns.utils import stringGen


class TestStringGen:
    """Unit tests for stringGen function."""

    def test_stringgen_default_length(self):
        """Test stringGen with default length (63)."""
        result = stringGen()

        assert isinstance(result, str)
        assert len(result) == 63

        # Check that all characters are from the expected charset
        charset = string.ascii_lowercase + string.digits
        for char in result:
            assert char in charset

    def test_stringgen_custom_length(self):
        """Test stringGen with custom lengths."""
        # Test various lengths
        test_lengths = [1, 5, 10, 20, 50, 100]

        for length in test_lengths:
            result = stringGen(length)

            assert isinstance(result, str)
            assert len(result) == length

            # Check that all characters are from the expected charset
            charset = string.ascii_lowercase + string.digits
            for char in result:
                assert char in charset
