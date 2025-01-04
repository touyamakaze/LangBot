import asyncio
import os
import shutil
import re
import time
import sched
import threading
import traceback

from mirai import Plain, Image, MessageChain
from pkg.plugin.models import *
from plugins.move_files.client import get_bangumi_img
from plugins.move_files.config import groups, source_folder, destination_folder_list, file_pattern, admin_qq
from pkg.plugin.host import EventContext, PluginHost
from pkg.plugin.context import register, BasePlugin, APIHost

"""
定时任务 移动Bangumi下载完成的文件
"""

poll_time = 300  # 每隔5分钟执行一次


def move_files(src_folder, dest_folder_list, pattern, logger) -> list:
    result_files = []
    for root, dirs, files in os.walk(src_folder):
        # print(f"Processing folder: {root}")
        for file in files:
            # print(f"Processing file: {file}")
            if re.match(pattern, file):
                src_file_path = os.path.join(root, file)
                dest_file_path = ''
                # 检查一下目标文件夹下是否已存在同名目录，存在的话，直接移动到已有的目录下
                for dest_folder in dest_folder_list:
                    dest_file_path_tmp = os.path.join(dest_folder, os.path.relpath(src_file_path, src_folder))

                    dest_dir = os.path.dirname(os.path.dirname(dest_file_path_tmp))
                    if not os.path.exists(dest_dir):
                        continue
                    dest_file_path = dest_file_path_tmp
                    break

                if not dest_file_path:
                    dest_file_path = os.path.join(dest_folder_list[0], os.path.relpath(src_file_path, src_folder))

                dest_dir = os.path.dirname(dest_file_path)
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)

                shutil.move(src_file_path, dest_file_path)
                logger.info("Moved file: {}".format(file))
                result_files.append(file)

    return result_files


def build_msg_chains(filename) -> list[MessageChain]:
    label_msg = ">订阅番剧更新：\n"
    msg_chains = []
    # 使用正则表达式提取“番剧名”、“S**”、“E**”信息
    match = re.match(r'(.*)S(\d+)E(\d+).*', filename)
    if match:
        title = match.group(1).strip()  # 提取“番剧名”并去除首尾空格
        season_number = int(match.group(2))
        episode_number = int(match.group(3))
        # 构造新的字符串
        result = "名称：{}\n季度：第{}季\n话数：第{}话".format(title, season_number, episode_number)
        img_path = get_bangumi_img(title, season_number)
        if 'error:' in img_path:
            msg_chains.append(MessageChain([Plain(label_msg), Plain(result)]))
            msg_chains.append(MessageChain([Plain(label_msg), Plain(img_path)]))
        else:
            msg_chains.append(MessageChain([Plain(label_msg), Image(path=img_path), Plain(result)]))
    else:
        msg_chains.append(MessageChain([Plain(label_msg), Plain(filename)]))

    return msg_chains


def timed_task(scheduler, task_event, logger, ctx: EventContext):
    while not task_event.is_set():
        logger.info("执行番剧文件移动任务")
        files = move_files(source_folder, destination_folder_list, file_pattern, logger)
        if len(files) != 0:
            for file_name in files:
                msg_chains = build_msg_chains(file_name)
                for group_id in groups:
                    logger.info("[group_{}] 发送番剧订阅：\n{}".format(group_id, str(msg_chains[0])))
                    try:
                        asyncio.run(ctx.send_group_message(group_id, msg_chains[0]))
                    except Exception:
                        logger.error("[group_{}] 发送番剧订阅 失败！！！\n{}".format(group_id, traceback.print_exc()))
                    time.sleep(3)
                    # 通知管理员出现了错误
                    if len(msg_chains) == 2:
                        logger.info("[person_{}] 发送错误报告：\n{}".format(admin_qq[0], str(msg_chains[1])))
                        try:
                            asyncio.run(ctx.send_person_message(admin_qq[0], msg_chains[1]))
                        except Exception:
                            logger.error("[person_{}] 发送错误报告 失败！！！\n{}".format(admin_qq[0], traceback.print_exc()))
                        time.sleep(3)
        time.sleep(poll_time)


def start_task(scheduler, task_event, logger, ctx: EventContext):
    logger.info("启动番剧文件移动任务")
    logger.info("加载订阅番剧更新消息，群组：" + str(groups))
    task_event.clear()
    threading.Thread(target=timed_task, args=(scheduler, task_event, logger, ctx), daemon=True).start()


def stop_task(task_event, logger):
    logger.info("停止番剧文件移动任务")
    task_event.set()


# 注册插件
@register(name="MoveFiles", description="自动移动Bangumi番剧文件", version="0.1", author="Touyama")
class MyPlugin(BasePlugin):

    task_event = None

    # 插件加载时触发
    def __init__(self, host: APIHost):
        self.task_event = threading.Event()

    # 当收到个人消息时触发
    @on(PersonCommandSent)
    def command_send(self, host: PluginHost, event: EventContext, command: str, **kwargs):
        if command == "move_file" or command == "mf":
            event.prevent_default()
            event.prevent_postorder()

            start_task(sched.scheduler(time.time, time.sleep), self.task_event, self.ap.logger, event)

            event.add_return("reply", "番剧文件移动任务已加载")

    # 插件卸载时触发
    def __del__(self):
        stop_task(self.task_event, self.ap.logger)
