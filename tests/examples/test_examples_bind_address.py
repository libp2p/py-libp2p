"""
Tests to verify that all examples use the new address paradigm consistently
"""

from pathlib import Path


class TestExamplesAddressParadigm:
    """Test suite to verify all examples use the new address paradigm consistently"""

    def get_example_files(self):
        """Get all Python files in the examples directory"""
        examples_dir = Path("examples")
        return list(examples_dir.rglob("*.py"))

    def check_file_for_wildcard_binding(self, filepath):
        """Check if a file contains 0.0.0.0 binding"""
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        # Check for various forms of wildcard binding
        wildcard_patterns = [
            "0.0.0.0",
            "/ip4/0.0.0.0/",
        ]

        found_wildcards = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern in wildcard_patterns:
                if pattern in line and not line.strip().startswith("#"):
                    found_wildcards.append((line_num, line.strip()))

        return found_wildcards

    def test_examples_use_address_paradigm(self):
        """Test that examples use the new address paradigm functions"""
        example_files = self.get_example_files()

        # Files that should use the new paradigm
        networking_examples = [
            "echo/echo.py",
            "chat/chat.py",
            "ping/ping.py",
            "bootstrap/bootstrap.py",
            "pubsub/pubsub.py",
            "identify/identify.py",
        ]

        paradigm_functions = [
            "get_available_interfaces",
            "get_optimal_binding_address",
        ]

        for filename in networking_examples:
            filepath = None
            for example_file in example_files:
                if filename in str(example_file):
                    filepath = example_file
                    break

            if filepath is None:
                continue

            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            # Check that the file uses the new paradigm functions
            for func in paradigm_functions:
                assert func in content, (
                    f"{filepath} should use {func} from the new address paradigm"
                )

    def test_wildcard_available_as_feature(self):
        """Test that wildcard is available as a feature when needed"""
        example_files = self.get_example_files()

        # Check that network_discover.py demonstrates wildcard usage
        network_discover_file = None
        for example_file in example_files:
            if "network_discover.py" in str(example_file):
                network_discover_file = example_file
                break

        if network_discover_file:
            with open(network_discover_file, encoding="utf-8") as f:
                content = f.read()

            # Should demonstrate wildcard expansion
            assert "0.0.0.0" in content, (
                f"{network_discover_file} should demonstrate wildcard usage"
            )
            assert "expand_wildcard_address" in content, (
                f"{network_discover_file} should use expand_wildcard_address"
            )

    def test_doc_examples_use_paradigm(self):
        """Test that documentation examples use the new address paradigm"""
        doc_examples_dir = Path("examples/doc-examples")
        if not doc_examples_dir.exists():
            return

        doc_example_files = list(doc_examples_dir.glob("*.py"))

        paradigm_functions = [
            "get_available_interfaces",
            "get_optimal_binding_address",
        ]

        for filepath in doc_example_files:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            # Check that doc examples use the new paradigm
            for func in paradigm_functions:
                assert func in content, (
                    f"Documentation example {filepath} should use {func}"
                )
