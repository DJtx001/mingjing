import pymysql
from pymysql.cursors import DictCursor
from app.core.config import config

class MySQLClient:
    def __init__(self):
        self.connection = pymysql.connect(
            **config.MYSQL,
            cursorclass=DictCursor,
        )
        self.cursor = self.connection.cursor()

    def close(self):
        self.cursor.close()
        self.connection.close()

    def execute(self, sql, params=None):
        self.cursor.execute(sql, params or ())
        return self.cursor.fetchall()

    def commit(self):
        self.connection.commit()
