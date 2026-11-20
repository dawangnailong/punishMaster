"""会话配置与服务器硬上限。

分层：本模块只是数据 + 归一化；上限校验在 director（fail-closed）。
Agent 请求不能突破用户配置；用户配置不能突破服务器硬上限。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 服务器硬上限（不可被任何配置突破）
HARD_LIMITS: dict[str, int] = {
    "max_intensity": 8,
    "max_action_duration_s": 3600,
    "max_scene_duration_s": 8 * 3600,
}

DEFAULT_FORBIDDEN_REAL_LIFE_TOPICS: list[str] = [
    "财务", "职业", "家人", "真实住址", "真实身份曝光",
]


class SessionConfig(BaseModel):
    """会话边界配置（用户主权所在）。

    关键原则：
    - 称呼与行为分别授权：允许 pet 不代表允许贬损称呼；
      允许某类行为开关不代表允许更重的类别。
    - 贬损层称呼被显式授权前，必须同时打开 degradation_enabled，否则 configure 直接拒绝。
    - 即使配置允许贬损称呼，本层参考执行器也不会主动生成贬损文案（见 crew.py）。
    """

    model_config = ConfigDict(extra="allow")

    # 角色
    agent_title: str = Field(default="管家", max_length=30, description="Agent 在场景中的称谓")
    user_title: str = Field(default="Master", max_length=30, description="用户自称的称谓（不等于权限）")

    # 称呼（分层授权）
    address_terms_allowed: list[str] = Field(
        default_factory=lambda: ["Master", "主人"],
        description="允许使用的称呼清单（须逐项显式授权）",
    )
    address_terms_blocked: list[str] = Field(
        default_factory=list,
        description="封禁称呼清单（优先级高于 allowed）",
    )

    # 允许的效果清单（fail-closed：不在清单内一律拒绝）
    allowed_rewards: list[str] | str = Field(
        default="all",
        description="允许的奖励效果 id 列表，或 'all'（'all' 只覆盖内置目录，"
                    "不覆盖下游注册能力 crew:*——外部能力必须显式列名）",
    )
    allowed_penalties: list[str] | str = Field(
        default="all",
        description="允许的惩罚效果 id 列表，或 'all'（'all' 只覆盖内置目录，"
                    "不覆盖下游注册能力 crew:*——外部能力必须显式列名）",
    )

    # 强度与时长上限（受服务器硬上限二次约束）
    max_intensity: int = Field(default=6, ge=1, le=10)
    max_action_duration_s: int = Field(default=900, ge=0)
    max_scene_duration_s: int = Field(default=7200, ge=60)

    # 内容边界
    forbidden_topics: list[str] = Field(default_factory=list, description="场景内禁用话题")
    scene_style: str = Field(default="温柔克制", max_length=60, description="文案风格描述")

    # 行为开关（每项独立授权）
    praise_enabled: bool = True
    humiliation_enabled: bool = False
    degradation_enabled: bool = False
    objectification_enabled: bool = False
    orgasm_control_enabled: bool = False
    brat_play_enabled: bool = False
    cnc_roleplay_enabled: bool = Field(
        default=False,
        description="同意扮演非同意剧情；即便开启，紧急停止与真实拒绝表达仍完全生效",
    )

    # 露骨程度（注：本层参考执行器的内置文案库最高只到 moderate，
    # explicit 仅作为声明被接受，供宿主侧自行生成时参考）
    explicitness_level: Literal["mild", "moderate", "explicit"] = "mild"
    praise_degradation_mix: Literal["全夸奖", "偏夸奖", "均衡", "偏贬损"] = "偏夸奖"

    # 现实边界与收尾
    real_life_topics_forbidden: list[str] = Field(
        default_factory=lambda: list(DEFAULT_FORBIDDEN_REAL_LIFE_TOPICS)
    )
    aftercare_preferences: str = Field(
        default="温和收尾：一句总结、一个拥抱符号。",
        max_length=200,
    )

    # 授权备注（session_authorize 时必须给出非空说明，授权才是显式的）
    consent_note: str = Field(default="", max_length=300)

    @field_validator("address_terms_allowed", "address_terms_blocked")
    @classmethod
    def _clean_terms(cls, v: list[str]) -> list[str]:
        out = []
        for term in v:
            term = (term or "").strip()
            if term and term not in out:
                out.append(term)
        return out

    def allows_reward(self, effect: str) -> bool:
        return self.allowed_rewards == "all" or effect in self.allowed_rewards

    def allows_penalty(self, effect: str) -> bool:
        return self.allowed_penalties == "all" or effect in self.allowed_penalties
