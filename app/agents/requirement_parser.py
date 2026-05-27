from __future__ import annotations

import re
from collections import Counter

from app.models.schemas import ExtractedFeatures


class RequirementParserAgent:
    """Agent 1: parse unstructured requirement text into architecture signals."""

    KEYWORD_WEIGHTS = {
        "concurrency": {
            "无需高并发": -1.0,
            "不需要高并发": -1.0,
            "低并发": -0.75,
            "50 人": -0.55,
            "万人": 1.0,
            "高并发": 0.95,
            "并发": 0.8,
            "同时在线": 0.9,
            "同时上课": 0.85,
            "高吞吐": 0.85,
            "流量": 0.65,
            "秒杀": 0.9,
        },
        "realtime": {
            "实时": 1.0,
            "即时": 0.9,
            "消息": 0.72,
            "通知": 0.65,
            "低延迟": 0.95,
            "长连接": 0.75,
            "直播": 0.9,
            "互动": 0.62,
            "流畅": 0.65,
        },
        "reliability": {
            "可靠": 0.88,
            "高可用": 0.95,
            "容灾": 0.85,
            "一致性": 0.72,
            "事务": 0.7,
            "审计": 0.6,
            "稳定": 0.58,
        },
        "scalability": {
            "扩展": 0.9,
            "弹性": 0.82,
            "模块": 0.45,
            "快速迭代": 0.76,
            "多团队": 0.75,
            "云原生": 0.72,
            "万人": 0.68,
            "同时上课": 0.5,
            "平台": 0.25,
        },
        "data_intensity": {
            "数据": 0.62,
            "日志": 0.68,
            "ETL": 0.88,
            "分析": 0.68,
            "报表": 0.56,
            "流式": 0.78,
            "录播": 0.55,
            "回放": 0.45,
        },
        "ai_reasoning": {
            "智能": 0.72,
            "AI": 0.78,
            "诊断": 0.7,
            "推荐": 0.58,
            "推理": 0.72,
            "大模型": 0.82,
        },
    }

    DOMAIN_HINTS = {
        "即时通信": ["聊天", "消息", "即时通讯", "IM", "视频通话"],
        "电商交易": ["订单", "支付", "秒杀", "库存", "购物"],
        "数据分析": ["数据", "ETL", "日志", "报表", "分析"],
        "企业管理": ["管理", "审批", "权限", "员工", "后台"],
        "物联网": ["IoT", "设备", "传感器", "采集"],
        "AI 辅助系统": ["智能", "AI", "大模型", "诊断", "推荐"],
        "在线教育": ["在线教育", "上课", "直播", "录播", "课后互动"],
        "社交媒体": ["社交", "发帖", "点赞", "评论", "私信"],
    }

    def parse(self, requirement: str) -> ExtractedFeatures:
        text = requirement.strip()
        normalized = text.lower()
        scores: dict[str, float] = {}
        found_keywords: list[str] = []

        for attribute, mapping in self.KEYWORD_WEIGHTS.items():
            score = 0.0
            for keyword, weight in mapping.items():
                if keyword.lower() in normalized or keyword in text:
                    score += weight
                    found_keywords.append(keyword)
            scores[attribute] = round(max(min(score, 1.0), 0.0), 2)

        constraints = self._extract_constraints(text)
        data_flow = self._infer_data_flow(text)
        domain = self._infer_domain(text)
        ambiguity_notes = self._ambiguity_notes(text, scores)

        return ExtractedFeatures(
            domain=domain,
            keywords=sorted(set(found_keywords)),
            quality_attributes=scores,
            constraints=constraints,
            data_flow=data_flow,
            ambiguity_notes=ambiguity_notes,
        )

    def _extract_constraints(self, text: str) -> dict[str, object]:
        numbers = re.findall(r"(\d+|[一二三四五六七八九十百千万]+)\s*(万|千|百)?", text)
        deployment = []
        for keyword in ["跨平台", "云", "私有化", "容器", "移动端", "Web", "桌面端", "多端"]:
            if keyword.lower() in text.lower() or keyword in text:
                deployment.append(keyword)

        return {
            "scale_mentions": ["".join(match) for match in numbers[:5]],
            "deployment": deployment,
            "requires_high_availability": any(key in text for key in ["高可用", "可靠", "容灾", "稳定"]),
            "requires_future_extension": any(key in text for key in ["后期", "未来", "扩展", "新增", "迭代"]),
        }

    def _infer_data_flow(self, text: str) -> str:
        if any(key in text for key in ["实时", "消息", "事件", "流式", "通知", "设备", "直播", "互动", "私信"]):
            return "event_stream"
        if any(key in text for key in ["ETL", "批处理", "报表", "日志", "清洗"]):
            return "pipeline"
        if any(key in text for key in ["审批", "订单", "支付", "事务"]):
            return "transactional"
        return "request_response"

    def _infer_domain(self, text: str) -> str:
        counter: Counter[str] = Counter()
        for domain, hints in self.DOMAIN_HINTS.items():
            for hint in hints:
                if hint.lower() in text.lower() or hint in text:
                    counter[domain] += 1
        return counter.most_common(1)[0][0] if counter else "通用业务系统"

    def _ambiguity_notes(self, text: str, scores: dict[str, float]) -> list[str]:
        notes = []
        if len(text) < 24:
            notes.append("需求描述较短，建议补充用户规模、数据一致性和部署环境。")
        if scores["reliability"] == 0 and scores["concurrency"] >= 0.7:
            notes.append("存在高并发信号，但可靠性与容灾目标未明确。")
        if scores["scalability"] >= 0.7 and "部署" not in text and "云" not in text:
            notes.append("扩展性目标明确，但部署方式和服务治理要求未说明。")
        return notes
