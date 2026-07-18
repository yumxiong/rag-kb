"""
自定义异常类
"""


class CancellationError(Exception):
    """任务取消异常"""

    pass


class ProcessingError(Exception):
    """文档处理异常"""

    pass
