"""
Test file template - z_test.py
Simple test structure for quick testing
"""

import unittest


class TestBasic(unittest.TestCase):
    """Basic test case examples"""
    
    def test_addition(self):
        """Test basic addition"""
        self.assertEqual(1 + 1, 2)
    
    def test_string_operations(self):
        """Test string operations"""
        text = "hello"
        self.assertEqual(text.upper(), "HELLO")
        self.assertTrue(text.startswith("h"))
    
    def test_list_operations(self):
        """Test list operations"""
        items = [1, 2, 3]
        self.assertEqual(len(items), 3)
        self.assertIn(2, items)


if __name__ == "__main__":
    unittest.main()
