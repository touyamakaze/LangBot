import asyncio
import os
import json
import re
import traceback
from datetime import datetime
from pkg.platform.types import MessageChain, Plain, Image
from pkg.plugin.context import register, BasePlugin, APIHost
from pkg.plugin.events import *  # 导入事件类
from pkg.plugin.models import *
from plugins.file_change_record.config import file_config, admin_qq
from pkg.plugin.host import EventContext, PluginHost
import time
import sched
import threading
from mirai import Plain, Image, MessageChain

"""
定时任务 磁盘文件变化记录
"""


def get_folder_structure(folder_path):
    structure = {}
    for root, dirs, files in os.walk(folder_path):
        rel_root = os.path.relpath(root, folder_path)
        structure[rel_root] = {'folders': dirs, 'files': []}
        for file in files:
            file_path = os.path.join(root, file)
            rel_file_path = os.path.relpath(file_path, folder_path)
            structure[rel_root]['files'].append(rel_file_path)
    return structure


def save_structure_to_file(structure, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(structure, f, indent=4, ensure_ascii=False)


def load_structure_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def compare_structure(previous_structure, current_structure):
    changes = {'added_folders': [], 'removed_folders': [], 'added_files': [], 'removed_files': []}
    for folder, content in current_structure.items():
        if folder not in previous_structure:
            changes['added_folders'].append(folder)
            changes['added_files'].extend([os.path.join(folder, file) for file in content['files']])
        else:
            previous_files = previous_structure[folder]['files']
            current_files = content['files']
            added_files = [file for file in current_files if file not in previous_files]
            removed_files = [file for file in previous_files if file not in current_files]
            if added_files:
                changes['added_files'].extend([os.path.join(folder, file) for file in added_files])
            if removed_files:
                changes['removed_files'].extend([os.path.join(folder, file) for file in removed_files])
    for folder in previous_structure.keys():
        if folder not in current_structure:
            changes['removed_folders'].append(folder)
    return changes


def save_changes(changes, previous_structure_file, folder_path):
    save_structure_to_file(get_folder_structure(folder_path), previous_structure_file)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    changes_record_file = os.path.splitext(previous_structure_file)[0] + "_changes_record_{}.json".format(timestamp)
    save_structure_to_file(changes, changes_record_file)


def main(folder_path, previous_structure_file, logger):
    current_structure = get_folder_structure(folder_path)
    logger.info("------------------------------------------")
    changes = {}
    if os.path.exists(previous_structure_file):
        previous_structure = load_structure_from_file(previous_structure_file)
        changes = compare_structure(previous_structure, current_structure)
        if changes['added_folders'] or changes['added_files'] or changes['removed_folders'] or changes['removed_files']:
            logger.info("[{}] Changes detected:".format(folder_path))
            logger.info("Added folders:")
            for folder in changes['added_folders']:
                logger.info(os.path.join(folder_path, folder))
            logger.info("Removed folders:")
            for folder in changes['removed_folders']:
                logger.info(os.path.join(folder_path, folder))
            logger.info("Added files:")
            for file in changes['added_files']:
                logger.info(os.path.join(folder_path, file))
            logger.info("Removed files:")
            for file in changes['removed_files']:
                logger.info(os.path.join(folder_path, file))
            save_changes(changes, previous_structure_file, folder_path)
        else:
            logger.info("[{}] The structure file has not been changed.".format(folder_path))
    else:
        logger.info("[{}] The structure file has been initialized.".format(folder_path))
    logger.info("------------------------------------------")
    save_structure_to_file(current_structure, previous_structure_file)
    return changes


def group_strings_by_prefix1(lst):
    result = {}
    for string in lst:
        parts = string.split('\\')
        if len(parts) > 1:
            prefix = '\\'.join(parts[:-1])
            if prefix not in result:
                result[prefix] = []
            result[prefix].append(parts[-1])
    return result


def group_strings_by_prefix2(lst):
    result = {}
    for string in lst:
        parts = string.split('/')
        if len(parts) > 1:
            prefix = '/'.join(parts[:-1])
            if prefix not in result:
                result[prefix] = []
            result[prefix].append(parts[-1])
    return result


def get_msgs(added_folders, tag):
    result_msgs = []
    added_folders_dict = group_strings_by_prefix1(added_folders) if "\\" in str(
        added_folders) else group_strings_by_prefix2(added_folders)
    result_msgs.append(Plain(">新追加{}：".format(tag)))
    num = 0
    if "番剧" in tag:
        for key in added_folders_dict:
            folder_name = str(str(key.split("\\")[-1]).split("/")[-1])
            num += 1
            result_msgs.append(Plain("\n" + str(num) + ".{}：".format(folder_name)))
            for value in added_folders_dict[key]:
                value = str(str(value.split("\\")[-1]).split("/")[-1])
                match = re.match(r'(.*)S(\d+).*', value)
                if match:
                    title = match.group(1).strip()
                    season_number = int(match.group(2))
                    result_msgs.append(Plain("\n {} 第{}季".format(title, season_number)))
                else:
                    result_msgs.append(Plain("\n {}".format(value)))
    else:
        for key in added_folders_dict:
            folder_name = str(str(key.split("\\")[-1]).split("/")[-1])
            num += 1
            result_msgs.append(Plain("\n" + str(num) + ".{}：".format(folder_name)))
            for value in added_folders_dict[key]:
                value = str(str(value.split("\\")[-1]).split("/")[-1])
                result_msgs.append(Plain("\n {}".format(value)))
    return result_msgs


def timed_task(scheduler, task_event, logger, ctx: EventContext):
    while not task_event.is_set():
        # 每天定时触发任务(00:00)
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:
            logger.info("执行文件变化记录任务")
            for item in file_config:
                try:
                    changes = main(item["folder_path"], item["folder_structure_file_path"], logger)
                    if len(changes) == 0:
                        continue
                    if changes['added_folders']:
                        if "groups" in item:
                            result_msgs = get_msgs(changes['added_folders'], item["tag"])
                            for group_id in item["groups"]:
                                logger.info("[group_{}] 发送 {} 新增加的文件夹：\n{}".format(group_id, item["tag"],
                                                                                   str(MessageChain(result_msgs))))
                                try:
                                    asyncio.run(ctx.send_group_message(group_id, MessageChain(result_msgs)))
                                except Exception:
                                    logger.error("[group_{}] 发送 {} 新增加的文件夹 失败！！！\n{}".format(group_id, item["tag"],
                                                                                             traceback.print_exc()))
                                time.sleep(3)
                    if changes['removed_folders']:
                        removed_folders_msg = MessageChain(
                            [Plain(">有文件夹被删除或丢失：\n"), Plain('\n'.join(changes['removed_folders']))])
                        logger.info("[person_{}] 发送 {} 被删除或丢失的文件夹：\n{}".format(admin_qq[0], item["tag"],
                                                                               str(removed_folders_msg)))
                        try:
                            asyncio.run(ctx.send_person_message(admin_qq[0], removed_folders_msg))
                        except Exception:
                            logger.error("[person_{}] 发送 {} 被删除或丢失的文件夹 失败！！！\n{}".format(admin_qq[0], item["tag"],
                                                                                         traceback.print_exc()))
                        time.sleep(3)
                    if changes['removed_files']:
                        removed_files_msg = MessageChain(
                            [Plain(">有文件被删除或丢失：\n"), Plain('\n'.join(changes['removed_files']))])
                        logger.info(
                            "[person_{}] 发送 {} 被删除或丢失的文件：\n{}".format(admin_qq[0], item["tag"], str(removed_files_msg)))
                        try:
                            asyncio.run(ctx.send_person_message(admin_qq[0], removed_files_msg))
                        except Exception:
                            logger.error("[person_{}] 发送 {} 被删除或丢失的文件 失败！！！\n{}".format(admin_qq[0], item["tag"],
                                                                                        traceback.print_exc()))
                        time.sleep(3)
                except Exception as e:
                    logger.error(traceback.print_exc())
                    err_msg = MessageChain([Plain("文件变化记录任务：{} 出现错误：\nerror: {}".format(item["tag"], e))])
                    logger.info("[person_{}] 发送错误报告：\n{}".format(admin_qq[0], str(err_msg)))
                    try:
                        asyncio.run(ctx.send_person_message(admin_qq[0], err_msg))
                    except Exception:
                        logger.error("[person_{}] 发送错误报告 失败！！！\n{}".format(admin_qq[0], traceback.print_exc()))
        time.sleep(50)


def start_task(scheduler, task_event, logger, ctx: EventContext):
    logger.info("启动文件变化记录任务")
    for item in file_config:
        logger.info("加载新追加番剧更新消息：{}，群组：{}".format(item["tag"], str(item["groups"])))
    task_event.clear()
    threading.Thread(target=timed_task, args=(scheduler, task_event, logger, ctx), daemon=True).start()


def stop_task(task_event, logger):
    logger.info("停止文件变化记录任务")
    task_event.set()


# 注册插件
@register(name="FileChangeRecord", description="文件变化记录", version="0.1", author="Touyama")
class MyPlugin(BasePlugin):
    task_event = None

    # 插件加载时触发
    def __init__(self, host: APIHost):
        self.task_event = threading.Event()

    # 当收到个人消息时触发
    @on(PersonCommandSent)
    def command_send(self, host: PluginHost, event: EventContext, command: str, **kwargs):
        if command == "file_change_record" or command == "fcr":
            event.prevent_default()
            event.prevent_postorder()

            start_task(sched.scheduler(time.time, time.sleep), self.task_event, self.ap.logger, event)

            event.add_return("reply", "文件变化记录任务已加载")

    # 插件卸载时触发
    def __del__(self):
        stop_task(self.task_event, self.ap.logger)
