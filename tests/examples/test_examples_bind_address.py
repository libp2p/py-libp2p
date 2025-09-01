"""
Tests to verify that all examples use 127.0.0.1 instead of 0.0.0.0
"""

import ast
import os
from pathlib import Path


class TestExamplesBindAddress:
    """Test suite to verify all examples use secure bind addresses"""

    def get_example_files(self):
        """Get all Python files in the examples directory"""
        examples_dir = Path("examples")
        return list(examples_dir.rglob("*.py"))

    def check_file_for_wildcard_binding(self, filepath):
        """Check if a file contains 0.0.0.0 binding"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for various forms of wildcard binding
        wildcard_patterns = [
            '0.0.0.0',
            '/ip4/0.0.0.0/',
        ]
        
        found_wildcards = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern in wildcard_patterns:
                if pattern in line and not line.strip().startswith('#'):
                    found_wildcards.append((line_num, line.strip()))
        
        return found_wildcards

    def test_no_wildcard_binding_in_examples(self):
        """Test that no example files use 0.0.0.0 for binding"""
        example_files = self.get_example_files()
        
        # Skip certain files that might legitimately discuss wildcards
        skip_files = [
            'network_discover.py',  # This demonstrates wildcard expansion
        ]
        
        files_with_wildcards = {}
        
        for filepath in example_files:
            if any(skip in str(filepath) for skip in skip_files):
                continue
                
            wildcards = self.check_file_for_wildcard_binding(filepath)
            if wildcards:
                files_with_wildcards[str(filepath)] = wildcards
        
        # Assert no wildcards found
        if files_with_wildcards:
            error_msg = "Found wildcard bindings in example files:\n"
            for filepath, occurrences in files_with_wildcards.items():
                error_msg += f"\n{filepath}:\n"
                for line_num, line in occurrences:
                    error_msg += f"  Line {line_num}: {line}\n"
            
            assert False, error_msg

    def test_examples_use_loopback_address(self):
        """Test that examples use 127.0.0.1 for local binding"""
        example_files = self.get_example_files()
        
        # Files that should contain listen addresses
        files_with_networking = [
            'ping/ping.py',
            'chat/chat.py',
            'bootstrap/bootstrap.py',
            'pubsub/pubsub.py',
            'identify/identify.py',
        ]
        
        for filename in files_with_networking:
            filepath = None
            for example_file in example_files:
                if filename in str(example_file):
                    filepath = example_file
                    break
            
            if filepath is None:
                continue
                
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for proper loopback usage
            has_loopback = '127.0.0.1' in content or 'localhost' in content
            has_multiaddr_loopback = '/ip4/127.0.0.1/' in content
            
            assert has_loopback or has_multiaddr_loopback, \
                f"{filepath} should use loopback address (127.0.0.1)"

    def test_doc_examples_use_loopback(self):
        """Test that documentation examples use secure addresses"""
        doc_examples_dir = Path("examples/doc-examples")
        if not doc_examples_dir.exists():
            return
            
        doc_example_files = list(doc_examples_dir.glob("*.py"))
        
        for filepath in doc_example_files:
            wildcards = self.check_file_for_wildcard_binding(filepath)
            assert not wildcards, \
                f"Documentation example {filepath} contains wildcard binding"
