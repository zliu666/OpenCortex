"""
二分查找算法实现
包含迭代和递归两种实现方式，并附带完整的测试套件

二分查找是一种在有序数组中查找特定元素的高效算法
时间复杂度: O(log n)
空间复杂度: 迭代 O(1), 递归 O(log n)
"""


def binary_search_iterative(arr, target):
    """
    二分查找算法 - 迭代实现
    
    使用循环而非递归的方式实现二分查找，更加节省内存空间
    
    参数:
        arr (list): 已排序的列表（升序）
        target (int/float): 要查找的目标值
    
    返回:
        int: 如果找到目标值，返回其索引；否则返回 -1
    
    示例:
        >>> binary_search_iterative([1, 3, 5, 7, 9], 5)
        2
        >>> binary_search_iterative([1, 3, 5, 7, 9], 6)
        -1
    """
    # 初始化左右边界指针
    left = 0                    # 左边界：数组起始位置
    right = len(arr) - 1        # 右边界：数组末尾位置
    
    # 当左边界不超过右边界时，继续查找
    # 这是一个循环不变量：目标值一定在 [left, right] 范围内（如果存在）
    while left <= right:
        # 计算中间位置索引
        # 使用整数除法，确保索引为整数
        mid = (left + right) // 2
        
        # 找到目标值，直接返回索引
        if arr[mid] == target:
            return mid
        
        # 如果中间值小于目标值
        # 说明目标值在右半部分，更新左边界
        elif arr[mid] < target:
            left = mid + 1       # 排除中间位置及左边的所有元素
        
        # 如果中间值大于目标值
        # 说明目标值在左半部分，更新右边界
        else:
            right = mid - 1      # 排除中间位置及右边的所有元素
    
    # 循环结束仍未找到，返回 -1 表示不存在
    return -1


def binary_search_recursive(arr, target, left=0, right=None):
    """
    二分查找算法 - 递归实现
    
    使用递归调用的方式实现二分查找，代码更加简洁易懂
    
    参数:
        arr (list): 已排序的列表（升序）
        target (int/float): 要查找的目标值
        left (int): 查找范围的左边界，默认为 0
        right (int): 查找范围的右边界，默认为数组末尾
    
    返回:
        int: 如果找到目标值，返回其索引；否则返回 -1
    
    示例:
        >>> binary_search_recursive([1, 3, 5, 7, 9], 7)
        3
        >>> binary_search_recursive([1, 3, 5, 7, 9], 10)
        -1
    """
    # 处理右边界参数的默认值
    # 不能在函数参数中直接使用 len(arr) - 1，因为默认值在函数定义时计算
    if right is None:
        right = len(arr) - 1
    
    # 递归终止条件：查找范围为空
    # 当左边界超过右边界时，说明已经查找完所有可能的范围
    if left > right:
        return -1
    
    # 计算中间位置索引
    mid = (left + right) // 2
    
    # 找到目标值，返回索引（递归终止条件）
    if arr[mid] == target:
        return mid
    
    # 如果中间值小于目标值
    # 在右半部分递归查找
    elif arr[mid] < target:
        return binary_search_recursive(arr, target, mid + 1, right)
    
    # 如果中间值大于目标值
    # 在左半部分递归查找
    else:
        return binary_search_recursive(arr, target, left, mid - 1)


def run_test(name, func, arr, target, expected):
    """
    运行单个测试用例并显示结果
    
    参数:
        name (str): 测试用例的名称
        func (function): 要测试的函数
        arr (list): 测试数组
        target: 要查找的目标值
        expected: 期望的返回结果
    
    返回:
        bool: 测试是否通过
    """
    # 执行被测试的函数
    result = func(arr, target)
    
    # 判断测试结果是否符合预期
    status = "✓ 通过" if result == expected else "✗ 失败"
    
    # 格式化输出测试结果
    # :30 表示左对齐占30个字符宽度
    # :3 表示右对齐占3个字符宽度
    print(f"{name:30} 期望: {expected:3}, 实际: {result:3}  {status}")
    
    return result == expected


# 主程序入口
if __name__ == "__main__":
    """
    测试套件主程序
    包含多种测试场景，验证算法的正确性和健壮性
    """
    
    print("=" * 60)
    print("二分查找算法测试套件")
    print("=" * 60)
    
    # 定义各种测试用的数组
    test_arr = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]  # 基础测试数组
    single_element = [42]                             # 单元素数组
    empty_arr = []                                    # 空数组
    two_elements = [10, 20]                          # 双元素数组
    duplicate_elements = [1, 3, 3, 3, 5, 7, 9]       # 包含重复元素的数组
    
    # 显示测试数据
    print(f"\n基础测试数组: {test_arr}")
    print(f"单元素数组: {single_element}")
    print(f"双元素数组: {two_elements}")
    print(f"重复元素数组: {duplicate_elements}")
    print(f"空数组: {empty_arr}")
    
    # 迭代实现的测试用例列表
    # 每个测试用例是一个元组：(测试名称, 数组, 目标值, 期望结果)
    print("\n" + "=" * 60)
    print("迭代实现测试 (binary_search_iterative)")
    print("=" * 60)
    
    iterative_tests = [
        # 基础测试
        ("查找中间元素 (7)", test_arr, 7, 3),
        ("查找第一个元素 (1)", test_arr, 1, 0),
        ("查找最后一个元素 (19)", test_arr, 19, 9),
        
        # 边界值测试
        ("查找不存在的元素 (8)", test_arr, 8, -1),
        ("查找小于最小值 (0)", test_arr, 0, -1),
        ("查找大于最大值 (20)", test_arr, 20, -1),
        
        # 特殊数组测试
        ("空数组查找", empty_arr, 5, -1),
        ("单元素数组-找到", single_element, 42, 0),
        ("单元素数组-未找到", single_element, 99, -1),
        ("双元素数组-找第一个", two_elements, 10, 0),
        ("双元素数组-找第二个", two_elements, 20, 1),
        ("重复元素数组", duplicate_elements, 3, 3),  # 返回中间的3
        
        # 不同长度数组测试
        ("偶数长度数组", [2, 4, 6, 8], 6, 2),
        ("奇数长度数组", [2, 4, 6, 8, 10], 8, 3),
    ]
    
    # 执行迭代实现的所有测试
    iterative_passed = 0
    for name, arr, target, expected in iterative_tests:
        if run_test(name, binary_search_iterative, arr, target, expected):
            iterative_passed += 1
    
    print(f"\n迭代实现: {iterative_passed}/{len(iterative_tests)} 测试通过")
    
    # 递归实现的测试（使用相同的测试用例）
    print("\n" + "=" * 60)
    print("递归实现测试 (binary_search_recursive)")
    print("=" * 60)
    
    recursive_passed = 0
    for name, arr, target, expected in iterative_tests:
        if run_test(name, binary_search_recursive, arr, target, expected):
            recursive_passed += 1
    
    print(f"\n递归实现: {recursive_passed}/{len(iterative_tests)} 测试通过")
    
    # 验证两种实现的结果是否一致
    print("\n" + "=" * 60)
    print("一致性验证")
    print("=" * 60)
    
    # 一致性测试用例
    consistency_tests = [
        ([1, 2, 3, 4, 5], 3),          # 正常情况
        ([1, 2, 3, 4, 5], 6),          # 不存在
        ([], 1),                        # 空数组
        ([100], 100),                   # 单元素存在
        ([10, 20, 30, 40, 50, 60], 25), # 中间不存在
    ]
    
    all_consistent = True
    for arr, target in consistency_tests:
        # 分别用两种实现进行查找
        iter_result = binary_search_iterative(arr, target)
        rec_result = binary_search_recursive(arr, target)
        
        # 检查结果是否一致
        consistent = iter_result == rec_result
        status = "✓ 一致" if consistent else "✗ 不一致"
        
        # 显示比较结果
        print(f"数组 {str(arr):20}, 目标 {target:3}: "
              f"迭代={iter_result:3}, 递归={rec_result:3}  {status}")
        
        if not consistent:
            all_consistent = False
    
    # 输出测试总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    total_tests = len(iterative_tests) * 2  # 两种实现
    total_passed = iterative_passed + recursive_passed
    
    print(f"总测试数: {total_tests}")
    print(f"通过: {total_passed}")
    print(f"失败: {total_tests - total_passed}")
    print(f"通过率: {total_passed/total_tests*100:.1f}%")
    print(f"实现一致性: {'✓ 通过' if all_consistent else '✗ 失败'}")
    
    # 输出实现对比和使用建议
    print("\n" + "=" * 60)
    print("实现方式对比:")
    print("-" * 60)
    print("迭代实现:")
    print("  - 时间复杂度: O(log n)")
    print("  - 空间复杂度: O(1)")
    print("  - 优点: 不使用调用栈，内存效率高，适合大数据集")
    print("  - 缺点: 代码结构相对复杂")
    print()
    print("递归实现:")
    print("  - 时间复杂度: O(log n)")
    print("  - 空间复杂度: O(log n) - 递归调用栈")
    print("  - 优点: 代码简洁，易于理解，适合教学和算法演示")
    print("  - 缺点: 可能有栈溢出风险（对于极大数组）")
    print()
    print("使用建议:")
    print("  - 生产环境推荐使用迭代实现（更稳定、更高效）")
    print("  - 学习和理解算法时推荐递归实现（更直观）")
    print("  - 如果数据量不大（<100万），两种实现性能差异可忽略")
    print("=" * 60)
