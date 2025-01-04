import sqlite3
import logging
import traceback


def get_bangumi_img(title, season_number) -> str:
    try:
        # 连接数据库（如果不存在则会创建）
        conn = sqlite3.connect('/SSD/Docker/Au­toBangumi/data/data.db')

        # 创建一个游标对象
        cursor = conn.cursor()

        try:
            # 执行查询
            cursor.execute("""
                SELECT `poster_link` FROM `bangumi` WHERE `official_title` = '{}' AND `season` = '{}'"""
                           .format(title, season_number))

            # 获取查询结果
            result = cursor.fetchone()

            # 打印结果
            if len(result) != 0:
                return '/SSD/Docker/Au­toBangumi/data/' + str(result[0])
            else:
                return ''

        except Exception as e1:
            logging.error(traceback.print_exc())
            return "get_bangumi_img() SQL error: {}".format(e1)

        finally:
            # 关闭游标和连接
            cursor.close()
            conn.close()

    except Exception as e2:
        logging.error(traceback.print_exc())
        return "get_bangumi_img() error: {}".format(e2)
