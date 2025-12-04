#!/usr/bin/env python3
"""数据库清理工具 - 清除旧的测评数据"""

import sqlite3
import os
import sys

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), 'depression.db')

def clean_all_test_data():
    """清空所有测评数据（保留用户信息）"""
    print("=" * 60)
    print("清空所有测评数据")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print("✗ 错误：数据库文件不存在！")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 统计数据
        cursor.execute("SELECT COUNT(*) FROM test")
        total_before = cursor.fetchone()[0]
        print(f"\n当前测评记录总数: {total_before}")
        
        if total_before == 0:
            print("数据库已经是空的，无需清理。")
            conn.close()
            return
        
        # 确认操作
        print("\n⚠️  警告：此操作将删除所有测评数据（用户信息不受影响）")
        confirm = input("确认删除？输入 'YES' 继续: ")
        
        if confirm.strip() != 'YES':
            print("操作已取消。")
            conn.close()
            return
        
        # 删除所有测评数据
        cursor.execute("DELETE FROM test")
        deleted_count = cursor.rowcount
        
        # 重置自增ID（可选）
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='test'")
        
        conn.commit()
        
        # 验证
        cursor.execute("SELECT COUNT(*) FROM test")
        total_after = cursor.fetchone()[0]
        
        print(f"\n✓ 清理完成！")
        print(f"  - 删除记录数: {deleted_count}")
        print(f"  - 剩余记录数: {total_after}")
        print(f"  - ID 计数器已重置")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


def clean_incomplete_tests():
    """只删除未完成的测评记录"""
    print("=" * 60)
    print("清空未完成的测评记录")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print("✗ 错误：数据库文件不存在！")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 统计数据
        cursor.execute("SELECT COUNT(*) FROM test WHERE status != '已完成'")
        incomplete_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM test WHERE status = '已完成'")
        completed_count = cursor.fetchone()[0]
        
        print(f"\n未完成记录: {incomplete_count}")
        print(f"已完成记录: {completed_count}")
        
        if incomplete_count == 0:
            print("没有未完成的记录需要清理。")
            conn.close()
            return
        
        # 确认操作
        print(f"\n将删除 {incomplete_count} 条未完成的记录，保留 {completed_count} 条已完成的记录。")
        confirm = input("确认删除？输入 'YES' 继续: ")
        
        if confirm.strip() != 'YES':
            print("操作已取消。")
            conn.close()
            return
        
        # 删除未完成的记录
        cursor.execute("DELETE FROM test WHERE status != '已完成'")
        deleted_count = cursor.rowcount
        
        conn.commit()
        
        print(f"\n✓ 清理完成！")
        print(f"  - 删除未完成记录: {deleted_count}")
        print(f"  - 保留已完成记录: {completed_count}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


def clean_by_user():
    """按用户删除测评数据"""
    print("=" * 60)
    print("按用户清理测评数据")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print("✗ 错误：数据库文件不存在！")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 显示所有用户
        cursor.execute("SELECT id, name FROM userinfo")
        users = cursor.fetchall()
        
        print("\n用户列表:")
        for user_id, name in users:
            cursor.execute("SELECT COUNT(*) FROM test WHERE user_id=?", [user_id])
            test_count = cursor.fetchone()[0]
            print(f"  {user_id}. {name} - {test_count} 条测评记录")
        
        # 选择用户
        user_id = input("\n输入要清理的用户ID: ").strip()
        
        if not user_id.isdigit():
            print("无效的用户ID。")
            conn.close()
            return
        
        user_id = int(user_id)
        
        cursor.execute("SELECT COUNT(*) FROM test WHERE user_id=?", [user_id])
        test_count = cursor.fetchone()[0]
        
        if test_count == 0:
            print(f"用户ID {user_id} 没有测评记录。")
            conn.close()
            return
        
        # 确认操作
        print(f"\n将删除用户ID {user_id} 的 {test_count} 条测评记录。")
        confirm = input("确认删除？输入 'YES' 继续: ")
        
        if confirm.strip() != 'YES':
            print("操作已取消。")
            conn.close()
            return
        
        # 删除指定用户的测评数据
        cursor.execute("DELETE FROM test WHERE user_id=?", [user_id])
        deleted_count = cursor.rowcount
        
        conn.commit()
        
        print(f"\n✓ 清理完成！")
        print(f"  - 删除记录数: {deleted_count}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


def show_menu():
    """显示菜单"""
    print("\n" + "=" * 60)
    print("数据库清理工具")
    print("=" * 60)
    print("\n请选择操作:")
    print("  1. 清空所有测评数据（保留用户信息）")
    print("  2. 只删除未完成的测评记录")
    print("  3. 按用户删除测评数据")
    print("  4. 退出")
    print("\n" + "=" * 60)


if __name__ == '__main__':
    while True:
        show_menu()
        choice = input("\n输入选项 (1-4): ").strip()
        
        if choice == '1':
            clean_all_test_data()
        elif choice == '2':
            clean_incomplete_tests()
        elif choice == '3':
            clean_by_user()
        elif choice == '4':
            print("\n退出程序。")
            break
        else:
            print("\n无效的选项，请重新输入。")
        
        input("\n按回车键继续...")

