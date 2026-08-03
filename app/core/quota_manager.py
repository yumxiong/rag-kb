"""
用户配额管理模块
实现基于IP地址或用户标识的使用次数限制
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from threading import Lock
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


@dataclass
class QuotaInfo:
    """用户配额信息"""

    user_id: str
    used_count: int = 0
    daily_limit: int = 5
    last_reset_date: str = ""
    first_use_time: str = ""
    last_use_time: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "QuotaInfo":
        return cls(**data)


class QuotaManager:
    """配额管理器"""

    def __init__(self, storage_path: str = "./data/quotas", daily_limit: int = 5):
        self.storage_path = storage_path
        self.daily_limit = daily_limit
        self._lock = Lock()

        # 确保存储目录存在
        os.makedirs(storage_path, exist_ok=True)
        self._quota_file = os.path.join(storage_path, "user_quotas.json")

        # 加载现有配额数据
        self._quotas = self._load_quotas()

    def _load_quotas(self) -> Dict[str, QuotaInfo]:
        """加载配额数据"""
        if not os.path.exists(self._quota_file):
            return {}

        try:
            with open(self._quota_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    user_id: QuotaInfo.from_dict(quota_data)
                    for user_id, quota_data in data.items()
                }
        except Exception as e:
            logger.error(f"Failed to load quotas: {e}")
            return {}

    def _save_quotas(self):
        """保存配额数据"""
        try:
            data = {user_id: quota.to_dict() for user_id, quota in self._quotas.items()}
            with open(self._quota_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save quotas: {e}")

    def _get_user_id(self, request_info: Dict) -> str:
        """生成用户唯一标识（基于IP地址和User-Agent的哈希）"""
        ip = request_info.get("client_ip", "unknown")
        user_agent = request_info.get("user_agent", "")

        # 创建用户指纹
        fingerprint = f"{ip}:{user_agent}"
        return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]

    def _is_new_day(self, last_date: str) -> bool:
        """检查是否是新的一天"""
        if not last_date:
            return True

        try:
            last_dt = datetime.fromisoformat(last_date)
            today = datetime.now().date()
            return last_dt.date() < today
        except (TypeError, ValueError):
            return True

    def check_and_increment(
        self, request_info: Dict, has_custom_key: bool = False
    ) -> Tuple[bool, QuotaInfo]:
        """
        检查配额并增加使用次数

        Args:
            request_info: 请求信息 (client_ip, user_agent等)
            has_custom_key: 是否使用了自定义API Key

        Returns:
            (是否允许使用, 用户配额信息)
        """
        # 如果用户提供了自定义API Key，则不受配额限制
        if has_custom_key:
            # 创建临时配额信息用于返回
            temp_quota = QuotaInfo(
                user_id="custom_key_user",
                used_count=0,
                daily_limit=999999,  # 无限制
                last_reset_date=datetime.now().isoformat(),
            )
            return True, temp_quota

        with self._lock:
            user_id = self._get_user_id(request_info)
            current_time = datetime.now().isoformat()

            # 获取或创建用户配额信息
            if user_id not in self._quotas:
                self._quotas[user_id] = QuotaInfo(
                    user_id=user_id,
                    daily_limit=self.daily_limit,
                    first_use_time=current_time,
                )

            quota = self._quotas[user_id]

            # 检查是否需要重置（新的一天）
            if self._is_new_day(quota.last_reset_date):
                quota.used_count = 0
                quota.last_reset_date = current_time
                logger.info(f"Reset quota for user {user_id[:8]}...")

            # 检查是否超出配额
            if quota.used_count >= quota.daily_limit:
                logger.warning(
                    f"User {user_id[:8]}... exceeded quota: "
                    f"{quota.used_count}/{quota.daily_limit}"
                )
                return False, quota

            # 增加使用次数
            quota.used_count += 1
            quota.last_use_time = current_time

            # 保存数据
            self._save_quotas()

            logger.info(
                f"User {user_id[:8]}... used {quota.used_count}/{quota.daily_limit}"
            )
            return True, quota

    def get_quota_info(self, request_info: Dict) -> QuotaInfo:
        """获取用户配额信息"""
        user_id = self._get_user_id(request_info)

        with self._lock:
            if user_id not in self._quotas:
                return QuotaInfo(user_id=user_id, daily_limit=self.daily_limit)

            quota = self._quotas[user_id]

            # 检查是否需要重置
            if self._is_new_day(quota.last_reset_date):
                quota.used_count = 0
                quota.last_reset_date = datetime.now().isoformat()
                self._save_quotas()

            return quota

    def reset_user_quota(self, request_info: Dict) -> bool:
        """重置用户配额（管理员功能）"""
        user_id = self._get_user_id(request_info)

        with self._lock:
            if user_id in self._quotas:
                self._quotas[user_id].used_count = 0
                self._quotas[user_id].last_reset_date = datetime.now().isoformat()
                self._save_quotas()
                logger.info(f"Reset quota for user {user_id[:8]}...")
                return True
            return False

    def get_all_quotas(self) -> Dict[str, Dict]:
        """获取所有用户配额统计（管理员功能）"""
        with self._lock:
            return {
                user_id[:8] + "...": quota.to_dict()
                for user_id, quota in self._quotas.items()
            }

    def set_daily_limit(self, new_limit: int):
        """设置每日配额限制"""
        self.daily_limit = new_limit

        # 更新现有用户的配额限制
        with self._lock:
            for quota in self._quotas.values():
                quota.daily_limit = new_limit
            self._save_quotas()

        logger.info(f"Updated daily limit to {new_limit}")


# 全局配额管理器实例
quota_manager = None


def get_quota_manager() -> QuotaManager:
    """获取配额管理器实例（延迟初始化）"""
    global quota_manager
    if quota_manager is None:
        from app.core.config import settings

        daily_limit = getattr(settings, "default_daily_quota", 5)
        quota_manager = QuotaManager(daily_limit=daily_limit)
    return quota_manager
