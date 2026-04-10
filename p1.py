#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
斐波那契数列实现模块

本模块提供了斐波那契数列的两种实现方式：递归和迭代。
斐波那契数列定义：F(0)=0, F(1)=1, F(n)=F(n-1)+F(n-2) for n>1

示例用法:
    >>> from p1 import fibonacci_iterative, fibonacci_recursive
    >>> fibonacci_iterative(10)
    55
    >>> fibonacci_recursive(10)
    55
"""

from typing import List, Union


def fibonacci_recursive(n: int) -> int:
    """
    使用递归方式计算斐波那契数列的第 n 项

    递归实现直接对应斐波那契数列的数学定义，代码简洁易懂。
    但由于存在重复计算，时间复杂度为 O(2^n)，仅适合小规模计算。

    Args:
        n: 要计算的项数（从 0 开始）
           - n <= 0 时返回 0
           - n = 1 时返回 1
           - n > 1 时返回 F(n-1) + F(n-2)

    Returns:
        int: 斐波那契数列第 n 项的值

    Examples:
        >>> fibonacci_recursive(0)
        0
        >>> fibonacci_recursive(1)
        1
        >>> fibonacci_recursive(10)
        55

    Note:
        警告：当 n > 30 时，递归方式会变得非常慢，建议使用迭代方式
    """
    # 基础情况：n <= 0 返回 0
    if n <= 0:
        return 0
    # 基础情况：n = 1 返回 1
    elif n == 1:
        return 1
    # 递归情况：F(n) = F(n-1) + F(n-2)
    else:
        return fibonacci_recursive(n - 1) + fibonacci_recursive(n - 2)


def fibonacci_iterative(n: int) -> int:
    """
    使用迭代方式计算斐波那契数列的第 n 项

    迭代实现通过循环依次计算每一项，避免了递归的重复计算问题。
    时间复杂度为 O(n)，空间复杂度为 O(1)，是推荐的实现方式。

    Args:
        n: 要计算的项数（从 0 开始）
           - n <= 0 时返回 0
           - n = 1 时返回 1
           - n > 1 时通过迭代计算

    Returns:
        int: 斐波那契数列第 n 项的值

    Examples:
        >>> fibonacci_iterative(0)
        0
        >>> fibonacci_iterative(1)
        1
        >>> fibonacci_iterative(10)
        55
        >>> fibonacci_iterative(100)
        354224848179261915075

    Note:
        这种方法高效且不会出现栈溢出问题，适合计算大数
    """
    # 处理边界情况
    if n <= 0:
        return 0
    elif n == 1:
        return 1

    # 初始化前两项：F(0) = 0, F(1) = 1
    a, b = 0, 1

    # 从第 2 项开始迭代计算到第 n 项
    # 每次迭代：a 保存前一项，b 保存当前项
    for _ in range(2, n + 1):
        # 计算新的一项：当前项 = 前一项 + 前前一项
        a, b = b, a + b

    # b 保存的就是第 n 项的值
    return b


def fibonacci_sequence(length: int, method: str = 'iterative') -> List[int]:
    """
    生成斐波那契数列

    根据指定的长度和方法生成斐波那契数列的前 n 项。

    Args:
        length: 要生成的数列长度
                - length <= 0 返回空列表
                - length = 1 返回 [0]
                - length = 2 返回 [0, 1]
        method: 计算方法，可选值：
                - 'iterative': 使用迭代方式（默认，推荐）
                - 'recursive': 使用递归方式（不推荐用于大数）

    Returns:
        List[int]: 包含斐波那契数列前 length 项的列表

    Raises:
        ValueError: 当 method 参数不是 'iterative' 或 'recursive' 时

    Examples:
        >>> fibonacci_sequence(5)
        [0, 1, 1, 2, 3]
        >>> fibonacci_sequence(10, method='iterative')
        [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

    Note:
        使用 'recursive' 方法时，length 建议不超过 25，否则会很慢
    """
    # 处理边界情况：长度小于等于 0 返回空列表
    if length <= 0:
        return []

    # 验证 method 参数
    if method not in ['iterative', 'recursive']:
        raise ValueError(f"method 必须是 'iterative' 或 'recursive'，当前值为 '{method}'")

    # 递归方式：逐项计算
    if method == 'recursive':
        return [fibonacci_recursive(i) for i in range(length)]

    # 迭代方式：直接生成整个序列（更高效）
    # 处理长度为 1 或 2 的特殊情况
    if length == 1:
        return [0]
    elif length == 2:
        return [0, 1]

    # 初始化序列：前两项已知
    sequence = [0, 1]

    # 逐项计算直到达到指定长度
    while len(sequence) < length:
        # 下一项 = 最后两项之和
        next_val = sequence[-1] + sequence[-2]
        sequence.append(next_val)

    return sequence


def test_fibonacci() -> None:
    """
    测试斐波那契数列函数

    运行一系列测试用例来验证函数的正确性和性能。
    包括基本功能测试、边界情况测试和性能对比。
    """
    print("=== 斐波那契数列函数测试 ===\n")

    # ========== 测试 1: 基本功能测试 ==========
    print("【测试 1】基本功能测试")
    print("-" * 50)

    # 定义测试用例：(n, expected_result)
    test_cases = [
        (0, 0),   # F(0) = 0
        (1, 1),   # F(1) = 1
        (2, 1),   # F(2) = F(1) + F(0) = 1
        (3, 2),   # F(3) = F(2) + F(1) = 2
        (5, 5),   # F(5) = 5
        (10, 55), # F(10) = 55
        (15, 610),# F(15) = 610
    ]

    print(f"{'n':>4} | {'期望值':>8} | {'递归结果':>8} | {'迭代结果':>8} | {'状态':<4}")
    print("-" * 50)

    all_passed = True
    for n, expected in test_cases:
        # 分别使用递归和迭代方式计算
        result_recursive = fibonacci_recursive(n)
        result_iterative = fibonacci_iterative(n)

        # 检查结果是否正确
        recursive_ok = result_recursive == expected
        iterative_ok = result_iterative == expected
        status = "✓" if (recursive_ok and iterative_ok) else "✗"

        if not (recursive_ok and iterative_ok):
            all_passed = False

        # 格式化输出
        print(f"{n:4d} | {expected:8d} | {result_recursive:8d} | {result_iterative:8d} | {status:<4}")

    print(f"\n测试结果: {'全部通过 ✓' if all_passed else '存在失败 ✗'}\n")

    # ========== 测试 2: 数列生成测试 ==========
    print("【测试 2】数列生成测试")
    print("-" * 50)

    # 测试生成前 10 项
    sequence = fibonacci_sequence(10)
    expected_seq = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

    print(f"生成前 10 项: {sequence}")
    print(f"期望结果:     {expected_seq}")
    print(f"状态: {'✓ 通过' if sequence == expected_seq else '✗ 失败'}\n")

    # ========== 测试 3: 边界情况测试 ==========
    print("【测试 3】边界情况测试")
    print("-" * 50)

    # 测试 n = 0
    result_0_recursive = fibonacci_recursive(0)
    result_0_iterative = fibonacci_iterative(0)
    print(f"n = 0:  递归={result_0_recursive}, 迭代={result_0_iterative}, 期望=0, "
          f"状态={'✓' if result_0_recursive == 0 and result_0_iterative == 0 else '✗'}")

    # 测试负数
    result_neg_recursive = fibonacci_recursive(-1)
    result_neg_iterative = fibonacci_iterative(-1)
    print(f"n = -1: 递归={result_neg_recursive}, 迭代={result_neg_iterative}, 期望=0, "
          f"状态={'✓' if result_neg_recursive == 0 and result_neg_iterative == 0 else '✗'}")

    # 测试空序列
    empty_seq = fibonacci_sequence(0)
    print(f"长度=0:  结果={empty_seq}, 期望=[], 状态={'✓' if empty_seq == [] else '✗'}")

    # 测试长度为 1 的序列
    single_seq = fibonacci_sequence(1)
    print(f"长度=1:  结果={single_seq}, 期望=[0], 状态={'✓' if single_seq == [0] else '✗'}\n")

    # ========== 测试 4: 性能对比测试 ==========
    print("【测试 4】性能对比测试（计算第 30 项）")
    print("-" * 50)

    import time

    # 测试递归方式的性能
    print("计算 fibonacci(30)...")
    start = time.time()
    result_recursive = fibonacci_recursive(30)
    time_recursive = time.time() - start
    print(f"  递归方式: 结果={result_recursive}, 耗时={time_recursive:.4f}秒")

    # 测试迭代方式的性能
    start = time.time()
    result_iterative = fibonacci_iterative(30)
    time_iterative = time.time() - start
    print(f"  迭代方式: 结果={result_iterative}, 耗时={time_iterative:.6f}秒")

    # 计算性能提升倍数
    speedup = time_recursive / time_iterative if time_iterative > 0 else float('inf')
    print(f"  结论: 迭代方式比递归方式快 {speedup:.1f} 倍\n")

    # ========== 测试 5: 大数计算测试 ==========
    print("【测试 5】大数计算测试")
    print("-" * 50)

    # 测试计算较大的数
    test_values = [40, 50, 100]
    for n in test_values:
        result = fibonacci_iterative(n)
        print(f"fibonacci({n:3d}) = {result}")

    print()

    # ========== 测试总结 ==========
    print("=" * 50)
    print("测试完成！所有测试用例已执行完毕。")
    print("=" * 50)


if __name__ == "__main__":
    """
    主程序入口

    当直接运行此脚本时，执行测试函数。
    可以作为模块导入时，测试函数不会自动运行。
    """
    test_fibonacci()
