"""基本算术运算模块。"""


def add(a: float, b: float) -> float:
    """返回 a + b。"""
    return a + b


def subtract(a: float, b: float) -> float:
    """返回 a - b。"""
    return a - b


def multiply(a: float, b: float) -> float:
    """返回 a * b。"""
    return a * b


def divide(a: float, b: float) -> float | None:
    """返回 a / b，除零时返回 None。"""
    if b == 0:
        return None
    return a / b


if __name__ == "__main__":
    print(f"add(2, 3) = {add(2, 3)}")
    print(f"subtract(10, 4) = {subtract(10, 4)}")
    print(f"multiply(3, 7) = {multiply(3, 7)}")
    print(f"divide(20, 5) = {divide(20, 5)}")
    print(f"divide(10, 0) = {divide(10, 0)}")
