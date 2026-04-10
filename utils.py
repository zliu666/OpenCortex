"""实用工具函数模块。"""

import re


def is_palindrome(s: str) -> bool:
    """判断字符串是否为回文（忽略大小写和非字母数字字符）。"""
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', s).lower()
    return cleaned == cleaned[::-1]


def reverse_string(s: str) -> str:
    """反转字符串。"""
    return s[::-1]


def count_words(text: str) -> int:
    """统计文本中的单词数量。"""
    return len(text.split())


if __name__ == "__main__":
    print(f"is_palindrome('Racecar') = {is_palindrome('Racecar')}")
    print(f"is_palindrome('hello') = {is_palindrome('hello')}")
    print(f"reverse_string('abcde') = {reverse_string('abcde')}")
    print(f"count_words('hello world foo') = {count_words('hello world foo')}")
