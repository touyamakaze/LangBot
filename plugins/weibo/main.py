from plugins.weibo.weibo_util import *
from pkg.platform.types import MessageChain, Plain, Image
from pkg.plugin.context import register, BasePlugin, APIHost
from pkg.plugin.events import *  # 导入事件类
from pkg.plugin.models import on
from plugins.weibo.config import ban_msgs, weibo_config, admin_qq
from pkg.plugin.host import EventContext, PluginHost
import asyncio
import json
import requests
import re
import time
import sched
import threading
import traceback

"""
定时任务 订阅微博消息
"""

init_tags = []  # 存储已初始化的微博tag
msg_ids = []  # 存储用户发布的微博消息id
ALL_NUM = 10  # 获取用户发布的最新ALL_NUM条内容
CHECK_NUM = 5  # 检测前CHECK_NUM条内容是否有更新
poll_time = 300  # 每隔5分钟执行一次


# 获取微博信息
def get_msgs(config, logger, retries=3) -> list:
    tag = config['tag']
    effect_msgs = []
    if 'effectMsgs' in config:
        effect_msgs = config['effectMsgs']
    results = []

    # 爬取网址
    url = 'https://m.weibo.cn/api/container/getIndex?containerid=' + config['containerId']

    # 用text方法得到JSON字符串类型
    content = requests.get(url).text
    # 将其转换为python字典
    content_dic = json.loads(content)

    # 获取有效条数
    count = 0
    # 获取用户发布的最新n条内容
    for i in range(ALL_NUM):
        if len(content_dic['data']['cards']) <= i:
            break
        card = content_dic['data']['cards'][i]
        # 发布的微博type是 9
        if str(card['card_type']) == '9':
            count += 1
            # 此为我们分析数据存储格式之后，定义的变量以及变量值的获取
            url = card['scheme']
            user_content = card['mblog']
            if not tag in init_tags:
                msg_ids.append(str(user_content['id']))
            elif str(user_content['id']) in msg_ids:
                continue
            else:
                msg_ids.append(str(user_content['id']))
                if count > CHECK_NUM:
                    continue

                result_msgs = [Plain("{}\n>微博更新：".format(tag))]

                # 内容
                if user_content.get('text'):
                    content_str = str(user_content['text']).replace('<br /><br />', '\n').replace('<br />', '\n')
                    content_text = content_str.split('<')[0]
                    content_html = content_str[len(content_text):]
                    content_html = re.sub(r'<.*?>', '', content_html)
                    publish_content = content_text + content_html
                    if has_ban_msg(publish_content):
                        continue
                    if len(effect_msgs) != 0 and not has_effect_msg(publish_content, effect_msgs):
                        continue
                    result_msgs.append(Plain('\n' + content_processing(publish_content, tag, url)))

                # 图片
                if user_content.get('original_pic'):
                    pic_url = user_content['original_pic']
                    pic_ids = user_content['pic_ids']
                    result_msgs.append(Plain("\n"))
                    pic_path = get_image(pic_url, pic_ids, logger)
                    if pic_path:
                        result_msgs.append(Image(path=pic_path))

                # 含有转发微博
                if user_content.get('retweeted_status'):
                    retweeted_content = user_content.get('retweeted_status')

                    # 转发微博内容
                    if retweeted_content.get('text'):
                        retweeted_content_str = str(retweeted_content['text']).replace('<br /><br />', '\n').replace(
                            '<br />', '\n')
                        retweeted_content_text = retweeted_content_str.split('<')[0]
                        retweeted_content_html = retweeted_content_str[len(retweeted_content_text):]
                        retweeted_content_html = re.sub(r'<.*?>', '', retweeted_content_html)
                        retweeted_publish_content = retweeted_content_text + retweeted_content_html
                        if has_ban_msg(retweeted_publish_content):
                            continue
                        result_msgs.append(
                            Plain('\n\n>转发微博内容：\n' + content_processing(retweeted_publish_content, tag, url)))

                    # 转发微博图片
                    if retweeted_content.get('original_pic'):
                        retweeted_pic_url = retweeted_content['original_pic']
                        retweeted_pic_ids = retweeted_content['pic_ids']
                        result_msgs.append(Plain("\n"))
                        retweeted_pic_path = get_image(retweeted_pic_url, retweeted_pic_ids, logger)
                        if retweeted_pic_path:
                            result_msgs.append(Image(path=retweeted_pic_path))

                    # 转发视频图片
                    if retweeted_content.get('page_info') and (
                            retweeted_content.get('page_info').get('type') == 'video'):
                        retweeted_page_info = retweeted_content.get('page_info')
                        if retweeted_page_info.get('page_pic') and retweeted_page_info.get('page_pic').get('url'):
                            retweeted_page_pic_url = retweeted_page_info.get('page_pic').get('url')
                            retweeted_page_pic_path = get_image(retweeted_page_pic_url, None, logger)
                            if retweeted_page_pic_path:
                                result_msgs.append(Plain("\n"))
                                result_msgs.append(Image(path=retweeted_page_pic_path))

                # 含有视频图片
                if user_content.get('page_info') and (user_content.get('page_info').get('type') == 'video'):
                    page_info = user_content.get('page_info')
                    if page_info.get('page_pic') and page_info.get('page_pic').get('url'):
                        page_pic_url = page_info.get('page_pic').get('url')
                        page_pic_path = get_image(page_pic_url, None, logger)
                        if page_pic_path:
                            result_msgs.append(Plain("\n"))
                            result_msgs.append(Image(path=page_pic_path))

                result_msgs.append(Plain("\n链接：{}".format(url)))
                results.append(result_msgs)

    if not tag in init_tags:
        init_tags.append(tag)
        logger.info("{} 微博缓存为空，已加载至最新".format(tag))
    elif len(results) == 0:
        logger.info("未检测到 {} 微博更新".format(tag))

    return results


def timed_task(scheduler, task_event, logger, ctx: EventContext):
    while not task_event.is_set():
        logger.info("执行微博订阅任务")
        for item in weibo_config:
            msgs = []
            try:
                msgs = get_msgs(item, logger)
            except Exception as e1:
                logger.error("微博：{} 获取失败".format(item["tag"]))
                logger.error(traceback.print_exc())
                # 防止线程崩溃挂掉，如果出错重试3次，如果仍然不行继续下一个
                for i in range(1, 4):
                    try:
                        msgs = get_msgs(item, logger)
                        logger.info("微博：{} 重试{}次，获取成功".format(item["tag"], i))
                        break
                    except Exception as e2:
                        logger.error("微博：{} 重试{}次，获取失败".format(item["tag"], i))
                        logger.error(traceback.print_exc())
                        if i == 3:
                            err_msg = MessageChain(
                                [Plain("微博：{} 重试{}次，获取失败\nget_msgs() error: {}".format(item["tag"], i, e2))])
                            logger.info("[person_{}] 发送错误报告：\n{}".format(admin_qq[0], str(err_msg)))
                            try:
                                asyncio.run(ctx.send_person_message(admin_qq[0], err_msg))
                            except Exception:
                                logger.error("[person_{}] 发送错误报告 失败！！！\n{}".format(admin_qq[0], traceback.print_exc()))
            for msg in msgs:
                for group_id in item["groups"]:
                    logger.info("[group_{}] 发送 {} 微博订阅：\n{}".format(group_id, item["tag"], str(MessageChain(msg))))
                    try:
                        asyncio.run(ctx.send_group_message(group_id, MessageChain(msg)))
                    except Exception:
                        logger.error(
                            "[group_{}] 发送 {} 微博订阅 失败！！！\n{}".format(group_id, item["tag"], traceback.print_exc()))
                    time.sleep(3)
        time.sleep(poll_time)


def start_task(scheduler, task_event, logger, ctx: EventContext):
    logger.info("启动微博订阅任务")
    for item in weibo_config:
        logger.info("加载微博：{}，群组：{}".format(item["tag"], str(item["groups"])))
    task_event.clear()
    threading.Thread(target=timed_task, args=(scheduler, task_event, logger, ctx), daemon=True).start()


def stop_task(task_event, logger):
    logger.info("停止微博订阅任务")
    task_event.set()


# 注册插件
@register(name="Weibo", description="微博订阅", version="0.1", author="Touyama")
class MyPlugin(BasePlugin):
    task_event = None

    # 插件加载时触发
    def __init__(self, host: APIHost):
        self.task_event = threading.Event()

    # 当收到个人消息时触发
    @on(PersonCommandSent)
    def command_send(self, host: PluginHost, event: EventContext, command: str, **kwargs):
        if command == "weibo" or command == "wb":
            event.prevent_default()
            event.prevent_postorder()

            start_task(sched.scheduler(time.time, time.sleep), self.task_event, self.ap.logger, event)

            event.add_return("reply", "微博订阅任务已加载")

    # 插件卸载时触发
    def __del__(self):
        stop_task(self.task_event, self.ap.logger)
