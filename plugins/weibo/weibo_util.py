import os
import re
import time
import requests
from PIL import Image
import random
import string
from plugins.weibo.config import ban_msgs

"""
微博内容处理工具
"""

# 指定保存路径，保存在 download 文件夹下
pic_save_path = "download\\"


def get_image(original_pic, pic_ids, logger):
    # 获取当前项目的根目录（假设当前目录为项目根目录）
    save_dir = os.path.join(os.getcwd(), pic_save_path)

    # 如果 download 文件夹不存在，则创建该文件夹
    os.makedirs(save_dir, exist_ok=True)

    pic_paths = []
    base_url = '/'.join(original_pic.split('/')[:-1]) + '/'

    # 下载图片
    if pic_ids and len(pic_ids) > 0:
        for pic_id in pic_ids:
            pic_url = base_url + pic_id + ".jpg"
            save_path = download_image(pic_url, save_dir, logger)
            if save_path:
                pic_paths.append(save_path)
    else:
        save_path = download_image(original_pic, save_dir, logger)
        pic_paths.append(save_path)

    images = [Image.open(pic_path) for pic_path in pic_paths]

    # 拼接图片
    result_img = concatenate_images(images)

    # 保存结果
    characters = string.ascii_letters + string.digits
    name = ''.join(random.choice(characters) for _ in range(16))
    result_path = os.path.join(save_dir, name + ".jpg")
    result_img.save(result_path)
    return result_path


def download_image(url, save_dir, logger):
    # 获取文件名（从 URL 提取）组装完成保存路径
    save_path = os.path.join(save_dir, url.split("/")[-1])

    if download_image_retry(url, save_path, logger):
        return save_path
    else:
        return None


# 递归下载方法，最多重试 3 次
def download_image_retry(url, save_path, logger, retries=3) -> bool:
    try:
        # 发送 GET 请求
        response = requests.get(url, stream=True)

        # 如果请求成功（状态码 200），则保存文件
        if response.status_code == 200:
            with open(save_path, "wb") as file:
                for chunk in response.iter_content(1024):  # 每次读取 1KB
                    file.write(chunk)
            # logger.info("图片已成功保存到 {}".format(save_path))
            return True
        else:
            # logger.info("下载失败，状态码: {}".format(response.status_code))
            raise Exception("下载失败")

    except Exception as e:
        # 打印错误信息
        # logger.info("下载出现错误: {}".format(e))

        # 如果重试次数大于 0，继续递归调用
        if retries > 0:
            # logger.info("重试中... 剩余重试次数: {}".format(retries))
            time.sleep(2)  # 等待 2 秒后重试
            return download_image_retry(url, save_path, logger, retries - 1)
        else:
            # logger.info("达到最大重试次数，下载失败")
            return False


# 拼接图片
def concatenate_images(images):
    # 图片数量
    n = len(images)

    # 计算需要的行和列数
    if n == 1:
        return images[0]
    elif n == 2 or n == 3:
        rows, cols = 1, n
    elif n == 4:
        rows, cols = 2, 2
    elif n == 5:
        rows, cols = 2, 3
    elif n == 6:
        rows, cols = 2, 3
    elif n == 7 or n == 8:
        rows, cols = 3, 3
    elif n == 9:
        rows, cols = 3, 3
    else:
        # For larger numbers, we calculate rows and cols based on the rules
        rows = (n + 2) // 3  # Generally, 3 columns, and calculate rows accordingly
        cols = 3

    # 计算拼接后图像的宽度和高度(取最大图片的宽度和高度)
    img_width, img_height = images[0].size
    for image in images:
        img_width_tmp, img_height_tmp = image.size
        img_width = img_width_tmp if img_width_tmp > img_width else img_width
        img_height = img_height_tmp if img_height_tmp > img_height else img_height

    total_width = img_width * cols
    total_height = img_height * rows

    # 创建一个空白画布来放置拼接的图片
    new_img = Image.new('RGB', (total_width, total_height), (255, 255, 255))

    # 将图片按规则拼接到新画布上
    idx = 0
    for row in range(rows):
        for col in range(cols):
            # 计算每个图片的位置
            x = col * img_width
            y = row * img_height

            # 检查是否还有剩余图片，如果没有则跳过
            if idx < n:
                new_img.paste(images[idx], (x, y))
                idx += 1

    return new_img


# 获得完整的，有效的内容
def content_processing(content, tag, url):
    if "...全文" in content:
        all_content = get_all_content(url)
        if all_content:
            content = all_content

    # 去除无效信息
    # 包括：结尾所有的“#”包含的tag内容,以及“视频”字样
    text = content.replace("{}的微博视频".format(tag), "").rstrip()

    while text.endswith('#'):
        last_hash_index = text.rfind('#')  # 找到最后一个“#”的索引
        if last_hash_index > 0:  # 确保“#”不是字符串的第一个字符
            prev_hash_index = text.rfind('#', 0, last_hash_index - 1)  # 找到倒数第二个“#”的索引
            if prev_hash_index != -1:  # 确保找到了倒数第二个#
                text = text[:prev_hash_index] + text[last_hash_index + 1:]  # 删除最后一对“#”及其内容
            else:
                text = text[:last_hash_index]  # 如果没有找到倒数第二个“#”，则删除最后一个“#”
        else:
            text = text[:-1]  # 如果“#”是字符串的第一个字符，则删除最后一个“#”
        text = text.rstrip()

    text = text.rstrip()
    # 找到最后一个空格的位置
    last_space_index = text.rfind(' ')
    # 如果找到了空格，则去除空格后面的内容(主要是去除转发的微博视频)
    text = text[:last_space_index] if last_space_index != -1 and text[last_space_index:].endswith("的微博视频") else text
    return text


# 获取微博的完整内容
def get_all_content(url):
    # 爬取网址
    response = requests.get(url)

    if response.status_code != 200:
        return None

    html_content = response.text  # 获取 HTML 内容

    # 使用正则表达式提取以 "text" 开头，"textLength" 结尾的内容
    pattern = r'"text".*?"textLength"'  # 匹配以 "text" 开头，"textLength" 结尾的内容
    match = re.search(pattern, html_content, re.DOTALL)  # re.DOTALL 让 . 能匹配换行符

    if match:
        # 提取匹配的内容
        extracted_text = match.group(0)
        # 使用 splitlines() 分割字符串为行列表
        lines = extracted_text.splitlines()
        # 获取倒数第二行
        extracted_text = lines[-2]
        # 提取匹配的内容
        content_str = str(extracted_text).replace('<br /><br />', '\n').replace('<br />', '\n').split("\"text\": \"")[
                          1][:-2]
        content_text = content_str.split('<')[0]
        content_html = content_str[len(content_text):]
        content_html = re.sub(r'<.*?>', '', content_html)
        publish_content = content_text + content_html
        return publish_content
    else:
        return None


def has_ban_msg(msg):
    for ban_msg in ban_msgs:
        if ban_msg in msg:
            return True
    return False


def has_effect_msg(msg, effect_msgs):
    for effect_msg in effect_msgs:
        if effect_msg in msg:
            return True
    return False
