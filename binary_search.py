#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
二分查找算法实现

二分查找（Binary Search）是一种在有序数组中查找特定元素的高效算法。
它的时间复杂度为 O(log n)，空间复杂度为 O(1)。

原理：
1. 每次将查找范围缩小一半
2. 比较中间元素与目标值
3. 根据比较结果调整查找范围
"""

def binary_search(arr, target):
    """
    标准二分查找 - 迭代版本
    
    参数:
        arr: 已排序的数组（升序）
        target: 要查找的目标值
    
    返回:
        目标值的索引，如果未找到则返回 -1
    """
    left, right = 0, len(arr) - 1
    
    while left <= right:
        mid = left + (right - left) // 2  # 防止整数溢出
        
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    
    return -1


def binary_search_recursive(arr, target, left=0, right=None):
    """
    二分查找 - 递归版本
    
    参数:
        arr: 已排序的数组（升序）
        target: 要查找的目标值
        left: 左边界
        right: 右边界
    
    返回:
        目标值的索引，如果未找到则返回 -1
    """
    if right is None:
        right = len(arr) - 1
    
    if left > right:
        return -1
    
    mid = left + (right - left) // 2
    
    if arr[mid] == target:
        return mid
    elif arr[mid] < target:
        return binary_search_recursive(arr, target, mid + 1, right)
    else:
        return binary_search_recursive(arr, target, left, mid - 1)


def binary_search_first_occurrence(arr, target):
    """
    二分查找 - 查找第一个等于目标值的元素（处理重复元素）
    
    参数:
        arr: 已排序的数组（升序）
        target: 要查找的目标值
    
    返回:
        第一个匹配元素的索引，如果未找到则返回 -1
    """
    left, right = 0, len(arr) - 1
    result = -1
    
    while left <= right:
        mid = left + (right - left) // 2
        
        if arr[mid] == target:
            result = mid
            right = mid - 1  # 继续在左半部分查找
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    
    return result


def binary_search_last_occurrence(arr, target):
    """
    二分查找 - 查找最后一个等于目标值的元素（处理重复元素）
    
    参数:
        arr: 已排序的数组（升序）
        target: 要查找的目标值
    
    返回:
        最后一个匹配元素的索引，如果未找到则返回 -1
    """
    left, right = 0, len(arr) - 1
    result = -1
    
    while left <= right:
        mid = left + (right - left) // 2
        
        if arr[mid] == target:
            result = mid
            left = mid + 1  # 继续在右半部分查找
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    
    return result


def binary_search_insert_position(arr, target):
    """
    二分查找 - 查找目标值应插入的位置（保持有序）
    
    参数:
        arr: 已排序的数组（升序）
        target: 要插入的目标值
    
    返回:
        插入位置的索引
    """
    left, right = 0, len(arr)
    
    while left < right:
        mid = left + (right - left) // 2
        
        if arr[mid] < target:
            left = mid + 1
        else:
            right = mid
    
    return left


if __name__ == "__main__":
    # 测试用例
    test_arr = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    
    print("测试数组:", test_arr)
    print("=" * 50)
    
    # 测试标准二分查找
    print("\n1. 标准二分查找（迭代版本）:")
    for target in [7, 1, 19, 20, 0]:
        index = binary_search(test_arr, target)
        if index != -1:
            print(f"   目标值 {target} 的索引为: {index}")
        else:
            print(f"   目标值 {target} 未找到")
    
    # 测试递归版本
    print("\n2. 二分查找（递归版本）:")
    for target in [7, 1, 19, 20]:
        index = binary_search_recursive(test_arr, target)
        if index != -1:
            print(f"   目标值 {target} 的索引为: {index}")
        else:
            print(f"   目标值 {target} 未找到")
    
    # 测试查找第一个出现位置
    print("\n3. 查找第一个出现位置（处理重复元素）:")
    dup_arr = [1, 2, 3, 3, 3, 4, 5, 5, 6]
    print(f"   测试数组: {dup_arr}")
    for target in [3, 5, 7]:
        index = binary_search_first_occurrence(dup_arr, target)
        if index != -1:
            print(f"   目标值 {target} 的第一个索引为: {index}")
        else:
            print(f"   目标值 {target} 未找到")
    
    # 测试查找最后一个出现位置
    print("\n4. 查找最后一个出现位置（处理重复元素）:")
    for target in [3, 5, 7]:
        index = binary_search_last_occurrence(dup_arr, target)
        if index != -1:
            print(f"   目标值 {target} 的最后一个索引为: {index}")
        else:
            print(f"   目标值 {target} 未找到")
    
    # 测试查找插入位置
    print("\n5. 查找插入位置:")
    insert_arr = [1, 3, 5, 7, 9]
    print(f"   测试数组: {insert_arr}")
    for target in [0, 4, 7, 10]:
        pos = binary_search_insert_position(insert_arr, target)
        print(f"   目标值 {target} 应插入索引: {pos}")
    
    print("\n" + "=" * 50)
    print("所有测试完成！")
