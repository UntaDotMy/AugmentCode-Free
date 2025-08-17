"""
文件清理模块 - 安全删除和强制删除功能
基于clean.js的文件删除功能，适配Python环境
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Dict
from .common_utils import IDEType, get_ide_paths, print_info, print_success, print_warning, print_error, create_backup
from .process_manager import ProcessManager

class FileCleaner:
    """文件清理器 - 安全删除和强制删除文件"""
    
    # 目标文件名
    TARGET_FILES = ['state.vscdb', 'state.vscdb.backup']
    
    def __init__(self):
        self.process_manager = ProcessManager()
    
    def clean_ide_files(self, ide_type: IDEType, force_mode: bool = False) -> Dict[str, int]:
        """
        清理指定IDE的状态文件
        
        Args:
            ide_type: IDE类型
            force_mode: 是否启用强制模式
            
        Returns:
            Dict[str, int]: 清理结果统计
        """
        print_info(f"开始清理 {ide_type.value} 状态文件...")
        
        paths = get_ide_paths(ide_type)
        if not paths:
            print_error(f"无法获取 {ide_type.value} 路径")
            return {"globalStorage": 0, "workspaceStorage": 0, "history": 0, "profile": 0}
        
        results = {
            "globalStorage": 0,
            "workspaceStorage": 0,
            "history": 0,
            "profile": 0
        }
        
        # 清理globalStorage
        global_storage_path = None
        if "state_db" in paths:
            global_storage_path = paths["state_db"].parent
            results["globalStorage"] = self._clean_global_storage(global_storage_path, force_mode)

        # 清理workspaceStorage
        if global_storage_path:
            workspace_storage_path = global_storage_path.parent / "workspaceStorage"
            if workspace_storage_path.exists():
                results["workspaceStorage"] = self._clean_workspace_storage(workspace_storage_path, force_mode)
        
        # VS Code Insiders 特殊清理
        if ide_type == IDEType.VSCODE_INSIDERS:
            # 清理History文件夹
            if "history" in paths and paths["history"].exists():
                results["history"] = self._clean_history_folder(paths["history"], force_mode)
            
            # 清理profile目录
            if "profile_dir" in paths:
                results["profile"] = self._clean_profile_directory(paths, force_mode)
        
        # VS Code Insiders 特殊清理
        if ide_type == IDEType.VSCODE:
            # 清理History文件夹
            if "history" in paths and paths["history"].exists():
                results["history"] = self._clean_history_folder(paths["history"], force_mode)
            
            # 清理profile目录
            if "profile_dir" in paths:
                results["profile"] = self._clean_profile_directory(paths, force_mode)
        
        return results
    
    def _clean_global_storage(self, global_storage_path: Path, force_mode: bool) -> int:
        """清理globalStorage目录"""
        print_info("清理 globalStorage...")
        
        if not global_storage_path.exists():
            print_error(f"globalStorage 目录不存在: {global_storage_path}")
            return 0
        
        deleted_count = 0
        for file_name in self.TARGET_FILES:
            file_path = global_storage_path / file_name
            if self.safe_delete_file(file_path, force_mode):
                deleted_count += 1
        
        print_success(f"globalStorage 清理完成，删除了 {deleted_count} 个文件")
        return deleted_count
    
    def _clean_workspace_storage(self, workspace_storage_path: Path, force_mode: bool) -> int:
        """清理workspaceStorage目录"""
        print_info("清理 workspaceStorage...")
        
        if not workspace_storage_path.exists():
            print_error(f"workspaceStorage 目录不存在: {workspace_storage_path}")
            return 0
        
        total_deleted = 0
        workspaces_processed = 0
        
        try:
            # 遍历所有工作区目录
            for workspace_dir in workspace_storage_path.iterdir():
                if workspace_dir.is_dir():
                    print_info(f"检查工作区: {workspace_dir.name}")
                    
                    deleted_in_workspace = 0
                    for file_name in self.TARGET_FILES:
                        file_path = workspace_dir / file_name
                        if self.safe_delete_file(file_path, force_mode):
                            deleted_in_workspace += 1
                            total_deleted += 1
                    
                    if deleted_in_workspace > 0:
                        workspaces_processed += 1
        
        except Exception as e:
            print_error(f"读取 workspaceStorage 目录失败: {e}")
            return 0
        
        print_success(f"workspaceStorage 清理完成:")
        print_info(f"  - 处理了 {workspaces_processed} 个工作区")
        print_info(f"  - 删除了 {total_deleted} 个文件")
        return total_deleted
    
    def safe_delete_file(self, file_path: Path, force_mode: bool = False) -> bool:
        """
        安全删除文件（带重试机制）
        
        Args:
            file_path: 文件路径
            force_mode: 是否启用强制模式
            
        Returns:
            bool: 是否成功删除
        """
        if not file_path.exists():
            return False
        
        print_info(f"尝试删除: {file_path}")
        
        # 第一步：尝试正常删除
        try:
            file_path.unlink()
            print_success(f"已删除: {file_path}")
            return True
        except (PermissionError, OSError) as e:
            if e.errno in [13, 32]:  # EACCES, EBUSY
                print_warning(f"删除失败: {file_path}")
                print_warning(f"错误: {e}")
                
                if force_mode:
                    print_info("启用强制模式，等待后重试...")
                    return self._force_delete_file(file_path)
                else:
                    print_info("可以尝试使用强制模式")
                    return False
            else:
                print_error(f"删除失败: {file_path} - {e}")
                return False
        except Exception as e:
            print_error(f"删除失败: {file_path} - {e}")
            return False
    
    def _force_delete_file(self, file_path: Path) -> bool:
        """强制删除文件（多种方法）"""
        # 等待一下，让可能的文件锁释放
        time.sleep(1)
        
        # 第二步：再次尝试正常删除
        try:
            file_path.unlink()
            print_success(f"延迟删除成功: {file_path}")
            return True
        except Exception:
            pass
        
        print_info("正常删除仍然失败，尝试查找并终止占用进程...")
        
        # 第三步：查找并终止占用文件的进程
        if os.name == 'nt':  # Windows
            occupying_processes = self.process_manager.find_processes_using_file(file_path)
            if occupying_processes:
                print_info(f"找到 {len(occupying_processes)} 个占用文件的进程")
                for proc in occupying_processes:
                    print_info(f"  {proc}")
                
                # 终止占用进程
                self._kill_occupying_processes(occupying_processes)
                time.sleep(2)
                
                # 再次尝试删除
                try:
                    file_path.unlink()
                    print_success(f"终止占用进程后删除成功: {file_path}")
                    return True
                except Exception:
                    pass
        
        # 第四步：使用系统命令强制删除
        if os.name == 'nt':  # Windows
            return self._windows_force_delete(file_path)
        else:
            return self._unix_force_delete(file_path)
    
    def _kill_occupying_processes(self, processes: List) -> None:
        """终止占用文件的进程"""
        for proc in processes:
            try:
                if os.name == 'nt':
                    subprocess.run(f'taskkill /F /PID {proc.pid}', shell=True, check=False, capture_output=True)
                else:
                    subprocess.run(['kill', '-KILL', proc.pid], check=False)
                print_info(f"已终止占用进程 PID: {proc.pid}")
            except Exception as e:
                print_warning(f"无法终止进程 {proc.pid}: {e}")
    
    def _windows_force_delete(self, file_path: Path) -> bool:
        """Windows强制删除方法"""
        methods = [
            {
                "name": "del命令",
                "command": f'del /F /Q "{file_path}"'
            },
            {
                "name": "PowerShell Remove-Item",
                "command": f'powershell -Command "Remove-Item -Path \'{file_path}\' -Force -ErrorAction SilentlyContinue"'
            },
            {
                "name": "attrib + del",
                "command": f'attrib -R -S -H "{file_path}" && del /F /Q "{file_path}"'
            }
        ]
        
        for method in methods:
            try:
                print_info(f"尝试使用 {method['name']} 删除文件...")
                subprocess.run(method["command"], shell=True, check=False, capture_output=True)
                
                # 检查文件是否真的被删除了
                if not file_path.exists():
                    print_success(f"使用 {method['name']} 强制删除成功: {file_path}")
                    return True
            except Exception as e:
                print_warning(f"{method['name']} 失败: {e}")
        
        # 最后的尝试：等待更长时间后再试
        print_info("等待5秒后最后一次尝试...")
        time.sleep(5)
        
        try:
            file_path.unlink()
            print_success(f"最终删除成功: {file_path}")
            return True
        except Exception as e:
            print_error(f"最终删除失败: {file_path}")
            print_error(f"最终错误: {e}")
            print_info("文件可能被系统进程锁定，建议重启后再试")
            return False
    
    def _unix_force_delete(self, file_path: Path) -> bool:
        """Unix系统强制删除方法"""
        try:
            # 尝试修改权限后删除
            os.chmod(file_path, 0o777)
            file_path.unlink()
            print_success(f"强制删除成功: {file_path}")
            return True
        except Exception as e:
            print_error(f"强制删除失败: {file_path} - {e}")
            return False

    def _clean_history_folder(self, history_path: Path, force_mode: bool) -> int:
        """
        清理VS Code Insiders的History文件夹
        
        Args:
            history_path: History文件夹路径
            force_mode: 是否启用强制模式
            
        Returns:
            int: 删除的项目数量
        """
        print_info(f"清理History文件夹: {history_path}")
        
        if not history_path.exists():
            print_warning(f"History文件夹不存在: {history_path}")
            return 0
        
        deleted_count = 0
        try:
            # 删除整个History文件夹
            if force_mode:
                shutil.rmtree(history_path, ignore_errors=True)
                print_success(f"已强制删除History文件夹: {history_path}")
                deleted_count = 1
            else:
                try:
                    shutil.rmtree(history_path)
                    print_success(f"已删除History文件夹: {history_path}")
                    deleted_count = 1
                except Exception as e:
                    print_warning(f"删除History文件夹失败: {e}")
                    print_info("可以尝试使用强制模式")
        except Exception as e:
            print_error(f"清理History文件夹时发生错误: {e}")
        
        return deleted_count

    def _clean_profile_directory(self, paths: Dict[str, Path], force_mode: bool) -> int:
        """
        清理VS Code Insiders的profile目录
        包括备份和清理extensions.json以及删除augment相关扩展
        
        Args:
            paths: 包含profile相关路径的字典
            force_mode: 是否启用强制模式
            
        Returns:
            int: 删除的项目数量
        """
        profile_dir = paths.get("profile_dir")
        extensions_dir = paths.get("profile_extensions")
        extensions_json = paths.get("profile_extensions_json")
        
        if not profile_dir or not profile_dir.exists():
            print_warning(f"Profile目录不存在: {profile_dir}")
            return 0
        
        print_info(f"清理Profile目录: {profile_dir}")
        deleted_count = 0
        
        # 1. 备份并清理 extensions.json
        if extensions_json and extensions_json.exists():
            deleted_count += self._clean_extensions_json(extensions_json, force_mode)
        
        # 2. 清理extensions目录中的augment相关扩展
        if extensions_dir and extensions_dir.exists():
            deleted_count += self._clean_profile_extensions(extensions_dir, force_mode)
        
        return deleted_count

    def _clean_extensions_json(self, extensions_json_path: Path, force_mode: bool) -> int:
        """
        备份并清理extensions.json文件中的augment相关条目
        
        Args:
            extensions_json_path: extensions.json文件路径
            force_mode: 是否启用强制模式
            
        Returns:
            int: 处理的文件数量
        """
        print_info(f"处理extensions.json: {extensions_json_path}")
        
        try:
            # 创建备份
            backup_path = create_backup(extensions_json_path)
            if not backup_path:
                print_error("无法创建extensions.json备份，跳过清理")
                return 0
            
            # 读取JSON文件
            with open(extensions_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            original_count = len(data) if isinstance(data, list) else 0
            
            # 过滤掉包含augment的条目
            if isinstance(data, list):
                filtered_data = []
                removed_items = []
                
                for item in data:
                    if isinstance(item, dict):
                        # 检查各种可能的字段
                        item_str = json.dumps(item, ensure_ascii=False).lower()
                        if 'augment' in item_str:
                            removed_items.append(item)
                        else:
                            filtered_data.append(item)
                    else:
                        # 如果是字符串，直接检查
                        if 'augment' not in str(item).lower():
                            filtered_data.append(item)
                        else:
                            removed_items.append(item)
                
                if removed_items:
                    print_info(f"从extensions.json中移除了 {len(removed_items)} 个augment相关条目:")
                    for item in removed_items:
                        print_info(f"  - {item}")
                    
                    # 写回清理后的数据
                    with open(extensions_json_path, 'w', encoding='utf-8') as f:
                        json.dump(filtered_data, f, indent=2, ensure_ascii=False)
                    
                    print_success(f"extensions.json清理完成，备份位于: {backup_path}")
                    return 1
                else:
                    print_info("extensions.json中未找到augment相关条目")
                    # 删除不必要的备份
                    backup_path.unlink()
                    return 0
            else:
                print_warning("extensions.json格式不是预期的数组格式")
                return 0
                
        except json.JSONDecodeError as e:
            print_error(f"extensions.json格式错误: {e}")
            return 0
        except Exception as e:
            print_error(f"处理extensions.json时发生错误: {e}")
            return 0

    def _clean_profile_extensions(self, extensions_dir: Path, force_mode: bool) -> int:
        """
        清理profile extensions目录中的augment相关扩展
        
        Args:
            extensions_dir: extensions目录路径
            force_mode: 是否启用强制模式
            
        Returns:
            int: 删除的扩展数量
        """
        print_info(f"清理扩展目录: {extensions_dir}")
        
        if not extensions_dir.exists():
            print_warning(f"扩展目录不存在: {extensions_dir}")
            return 0
        
        deleted_count = 0
        
        try:
            for item in extensions_dir.iterdir():
                if item.is_dir() and 'augment' in item.name.lower():
                    print_info(f"找到augment扩展: {item.name}")
                    
                    try:
                        if force_mode:
                            shutil.rmtree(item, ignore_errors=True)
                            print_success(f"已强制删除扩展: {item.name}")
                            deleted_count += 1
                        else:
                            shutil.rmtree(item)
                            print_success(f"已删除扩展: {item.name}")
                            deleted_count += 1
                    except Exception as e:
                        print_warning(f"删除扩展失败 {item.name}: {e}")
                        if not force_mode:
                            print_info("可以尝试使用强制模式")
        
        except Exception as e:
            print_error(f"遍历扩展目录时发生错误: {e}")
        
        if deleted_count > 0:
            print_success(f"从profile扩展目录删除了 {deleted_count} 个augment扩展")
        else:
            print_info("profile扩展目录中未找到augment相关扩展")
        
        return deleted_count
