"""Agent 1: Parse natural language requirements into structured architecture features.

Responsibilities:
- Input validation (non-empty, reasonable length)
- LLM-based semantic extraction (two-pass with strict mode)
- Pydantic schema validation via llm_client
- Internal consistency checks (domain vs keywords, capability count vs quality attributes)
- Regex + keyword fallback when LLM is unavailable
"""

from __future__ import annotations

import re
from typing import Any

from app.models.schemas import ExtractedFeatures
from app.services.llm_client import LLMClient


class RequirementParserAgent:
    """Parses free-text software requirements into structured ExtractedFeatures."""

    # ── Minimum viable requirement ──
    MIN_LENGTH = 5
    MAX_LENGTH = 8000

    # ── Keyword patterns for fallback extraction ──
    DOMAIN_PATTERNS: list[tuple[str, str]] = [
        (r"电商|购物|下单|支付|秒杀|库存", "电商交易"),
        (r"门店|鲜花|进销存|收银|会员", "门店管理"),
        (r"审批|流程|工单|OA|公文", "办公协同"),
        (r"视频|直播|弹幕|流媒体|转码", "流媒体"),
        (r"物联网|传感器|设备|边缘|MQTT", "物联网"),
        (r"社交|聊天|消息|朋友圈|动态", "社交网络"),
        (r"金融|支付|清算|风控|交易", "金融交易"),
        (r"医疗|患者|诊断|处方|挂号", "医疗健康"),
        (r"教育|课程|学生|教师|作业", "在线教育"),
        (r"物流|配送|快递|仓储|运单", "物流配送"),
    ]

    CONCURRENCY_SIGNALS = [
        (r"高并发|秒杀|抢购|千万|亿级|百万用户|峰值", 0.85),
        (r"多用户|并发|同时|多人|大量用户", 0.55),
        (r"单用户|个人|少量|小规模", 0.15),
    ]

    REALTIME_SIGNALS = [
        (r"实时|毫秒|低延迟|即时|实时推送", 0.85),
        (r"准实时|秒级|快速|及时", 0.45),
        (r"离线|批量|定时|异步|非实时", 0.1),
    ]

    SCALABILITY_SIGNALS = [
        (r"弹性|伸缩|扩展|增长|规模化|微服务|独立部署", 0.8),
        (r"后续扩展|未来|规划|二期", 0.4),
    ]

    BUSINESS_ACTION_PATTERN = re.compile(
        r"(录入|查询|选择|下单|审核|核验|扣费|统计|提醒|登记|分配|签收|汇总|管理|浏览|发布|上传|下载|预约|归还|租借|领用|退款|评价|跟踪|通知)"
    )

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    # ────────────────────────────── Public API ──────────────────────────────

    async def parse(self, requirement: str) -> ExtractedFeatures:
        """Main entry point: validate → LLM extract → consistency check → return."""
        self._validate_input(requirement)

        llm_error: str | None = None
        features = await self._extract_with_llm(requirement)
        if not features:
            llm_error = self.llm_client.last_error or "LLM 不可用"

        if features:
            consistency_issues = self._check_consistency(requirement, features)
            if consistency_issues:
                features = features.model_copy(
                    update={"ambiguity_notes": features.ambiguity_notes + consistency_issues}
                )

        if not features:
            features = self._fallback_extract(requirement)
            features = features.model_copy(
                update={
                    "ambiguity_notes": features.ambiguity_notes
                    + [
                        f"LLM 不可用，使用本地关键词兜底解析。LLM 错误：{llm_error}",
                        "quality_attributes 为估算值，建议人工复核。",
                    ]
                }
            )

        return features

    # ────────────────────────────── Validation ──────────────────────────────

    @staticmethod
    def _validate_input(requirement: str) -> None:
        """Raise ValueError if the input is clearly unusable."""
        stripped = requirement.strip()
        if len(stripped) < RequirementParserAgent.MIN_LENGTH:
            raise ValueError(f"需求文本过短（最少 {RequirementParserAgent.MIN_LENGTH} 个字符）")
        if len(stripped) > RequirementParserAgent.MAX_LENGTH:
            raise ValueError(f"需求文本过长（最多 {RequirementParserAgent.MAX_LENGTH} 个字符）")
        if stripped.count(" ") < 1 and len(stripped) < 20:
            raise ValueError("需求文本疑似关键词而非自然语言描述，请提供完整的业务场景说明。")

    # ────────────────────────────── LLM Extraction ──────────────────────────

    async def _extract_with_llm(self, requirement: str) -> ExtractedFeatures | None:
        """Two-pass extraction: relaxed first, strict retry on failure."""
        return await self.llm_client.extract_features(requirement)

    # ────────────────────────────── Fallback ───────────────────────────────

    @staticmethod
    def _fallback_extract(requirement: str) -> ExtractedFeatures:
        """Regex + keyword heuristics when LLM is completely unavailable."""
        text = requirement.strip()

        # Domain
        domain = "通用业务"
        for pattern, label in RequirementParserAgent.DOMAIN_PATTERNS:
            if re.search(pattern, text):
                domain = label
                break

        # Keywords: extract 2-6 character Chinese noun phrases
        keywords = list(
            dict.fromkeys(
                re.findall(r"[一-鿿]{2,6}", text)
            )
        )[:12]

        # Business capabilities
        capabilities = list(
            dict.fromkeys(RequirementParserAgent.BUSINESS_ACTION_PATTERN.findall(text))
        )
        if not capabilities:
            capabilities = ["业务处理", "数据管理"]

        # Quality attributes
        quality_attributes: dict[str, float] = {
            "concurrency": RequirementParserAgent._estimate(text, RequirementParserAgent.CONCURRENCY_SIGNALS, 0.3),
            "realtime": RequirementParserAgent._estimate(text, RequirementParserAgent.REALTIME_SIGNALS, 0.2),
            "reliability": 0.5,
            "scalability": RequirementParserAgent._estimate(text, RequirementParserAgent.SCALABILITY_SIGNALS, 0.3),
            "data_intensity": 0.3,
            "ai_reasoning": 0.0,
        }

        # Data flow
        if re.search(r"事件|消息|通知|推送|发布订阅", text):
            data_flow = "event_stream"
        elif re.search(r"流水线|ETL|清洗|转换|批处理", text):
            data_flow = "pipeline"
        elif re.search(r"事务|订单|支付|扣款|一致性", text):
            data_flow = "transactional"
        else:
            data_flow = "request_response"

        # Constraints
        constraints: dict[str, Any] = {
            "scale_mentions": [],
            "deployment": [],
            "requires_high_availability": bool(re.search(r"高可用|容灾|99\.|不宕机", text)),
            "requires_future_extension": bool(re.search(r"扩展|二期|未来|后续|规划", text)),
        }

        return ExtractedFeatures(
            domain=domain,
            keywords=keywords,
            business_capabilities=capabilities,
            architecture_drivers=[],
            topology_expectations={},
            quality_attributes=quality_attributes,
            constraints=constraints,
            data_flow=data_flow,
            ambiguity_notes=["使用本地关键词兜底解析，quality_attributes 为估算值"],
        )

    @staticmethod
    def _estimate(text: str, signals: list[tuple[str, float]], default: float) -> float:
        for pattern, value in signals:
            if re.search(pattern, text):
                return value
        return default

    # ─────────────────────────── Consistency ────────────────────────────────

    @staticmethod
    def _check_consistency(requirement: str, features: ExtractedFeatures) -> list[str]:
        """Return a list of consistency issues; empty list means no problems."""
        issues: list[str] = []

        # 1. Non-empty requirement should produce non-trivial features
        if not features.domain or features.domain in {"", "未知"}:
            issues.append("LLM 未能识别业务领域，请检查需求是否包含足够的业务上下文。")

        if not features.keywords:
            issues.append("LLM 未提取到关键词，需求可能缺乏技术或业务特征词。")

        if not features.business_capabilities:
            issues.append("LLM 未提取到业务能力，需求描述可能过于抽象。")

        # 2. Domain–keywords coherence
        if features.domain and features.keywords:
            if features.domain == "电商交易" and not any(
                kw in " ".join(features.keywords) for kw in ["订单", "支付", "商品", "库存", "购物"]
            ):
                issues.append("领域识别为电商，但关键词中缺少典型电商要素，可能存在误判。")

        # 3. Quality attributes sanity
        qa = features.quality_attributes
        capability_count = len([c for c in features.business_capabilities if str(c).strip()])

        if qa.get("concurrency", 0) >= 0.7 and capability_count <= 5:
            issues.append(
                f"高并发标记({qa['concurrency']})与业务能力数量({capability_count})不匹配，"
                "高并发系统通常有更丰富的业务链路，建议人工复核。"
            )

        if qa.get("concurrency", 0) <= 0.2 and qa.get("scalability", 0) >= 0.8:
            issues.append(
                "低并发但高扩展性标注存在矛盾，请确认需求中是否有明确的水平扩展或独立部署诉求。"
            )

        if qa.get("ai_reasoning", 0) >= 0.6 and not re.search(
            r"AI|模型|推理|预测|推荐|机器学习|深度学习|大模型", requirement
        ):
            issues.append("AI 推理标记较高，但需求原文中未检测到 AI 相关关键词。")

        # 4. Data flow vs capabilities consistency
        if features.data_flow == "event_stream" and not any(
            kw in " ".join(features.business_capabilities + features.keywords)
            for kw in ["事件", "消息", "通知", "推送", "流", "实时"]
        ):
            issues.append("数据流类型为 event_stream，但业务能力中未体现事件驱动特征。")

        return issues
