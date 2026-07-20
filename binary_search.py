"""
二分查找（Binary Search）实现模块。

提供对已排序序列进行高效查找的函数，时间复杂度 O(log n)。
支持精确查找和查找插入位置两种模式。
"""

from typing import TypeVar, Sequence, Optional

# 泛型类型变量，支持任意可比较类型的列表
T = TypeVar("T")


def binary_search(arr: Sequence[T], target: T) -> Optional[int]:
    """
    在已排序的序列中二分查找目标值，返回其索引。

    如果目标值存在则返回其索引，否则返回 None。
    若存在多个相同值，返回其中任意一个的索引。

    Args:
        arr: 已按升序排列的序列（支持 list、tuple 等）
        target: 要查找的目标值

    Returns:
        目标值的索引（0-based），未找到则返回 None

    Examples:
        >>> binary_search([1, 3, 5, 7, 9], 5)
        2
        >>> binary_search([1, 3, 5, 7, 9], 4) is None
        True
    """
    if not arr:
        return None

    left, right = 0, len(arr) - 1

    while left <= right:
        # 使用左中位数计算方式，避免整数溢出
        mid = left + (right - left) // 2
        mid_value = arr[mid]

        if mid_value == target:
            return mid
        elif mid_value < target:
            # 目标在右半区，收缩左边界
            left = mid + 1
        else:
            # 目标在左半区，收缩右边界
            right = mid - 1

    return None


def binary_search_leftmost(arr: Sequence[T], target: T) -> int:
    """
    在已排序序列中查找目标值第一次出现的位置（最左索引）。

    如果目标值不存在，返回应该插入的位置（保持有序）。
    此函数永远不会返回 -1，适合用于查找插入点。

    Args:
        arr: 已按升序排列的序列
        target: 要查找的目标值

    Returns:
        目标值第一次出现的索引，或应插入的位置索引

    Examples:
        >>> binary_search_leftmost([1, 2, 2, 2, 3], 2)
        1
        >>> binary_search_leftmost([1, 3, 5, 7], 4)
        2
    """
    left, right = 0, len(arr)

    while left < right:
        mid = left + (right - left) // 2
        if arr[mid] < target:
            left = mid + 1
        else:
            right = mid

    return left


def binary_search_rightmost(arr: Sequence[T], target: T) -> int:
    """
    在已排序序列中查找目标值最后一次出现之后的位置（最右索引 + 1）。

    如果目标值不存在，返回应该插入的位置。

    Args:
        arr: 已按升序排列的序列
        target: 要查找的目标值

    Returns:
        目标值最后一次出现之后的位置索引

    Examples:
        >>> binary_search_rightmost([1, 2, 2, 2, 3], 2)
        4
        >>> binary_search_rightmost([1, 3, 5, 7], 4)
        2
    """
    left, right = 0, len(arr)

    while left < right:
        mid = left + (right - left) // 2
        if arr[mid] <= target:
            left = mid + 1
        else:
            right = mid

    return left


# ============ 使用示例与简单测试 ============
if __name__ == "__main__":
    # 测试精确查找
    nums = [1, 3, 5, 7, 9, 11, 13]
    test_cases = [5, 1, 13, 4, 0, 15]

    print("=== 精确查找测试 ===")
    for x in test_cases:
        result = binary_search(nums, x)
        status = f"索引 {result}" if result is not None else "未找到"
        print(f"  查找 {x}: {status}")

    # 测试最左/最右查找
    dup_nums = [1, 2, 2, 2, 3, 4, 5]
    print("\n=== 重复元素查找测试 ===")
    print(f"  数组: {dup_nums}")
    print(f"  最左 2 的位置: {binary_search_leftmost(dup_nums, 2)}")
    print(f"  最右 2 之后:   {binary_search_rightmost(dup_nums, 2)}")
    print(f"  4 的插入位置:  {binary_search_leftmost(dup_nums, 4)}")

    # 空数组边缘测试
    print("\n=== 边缘情况测试 ===")
    print(f"  空数组查找 1: {binary_search([], 1)}")
    print(f"  空数组插入位置: {binary_search_leftmost([], 1)}")
