"""Authored offline research/provider adapters, never loaded by product commands."""

import sys
from pathlib import Path
from uuid import uuid4
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from test_workbench_pipeline import Provider, dispatches  # noqa: E402
from test_model_context_review import BODY  # noqa: E402
from test_advisory_guide import proposal  # noqa: E402
from travel_agent.preview.worker import run_job  # noqa: E402
from travel_agent.planning.suggestions import run_worker  # noqa: E402
from travel_agent.providers.llm import OpenAICompatibleProvider  # noqa: E402
from travel_agent.research.models import Candidate, DetailMaterial  # noqa: E402


def config():
    return OpenAICompatibleProvider(
        "https://api.deepseek.com", "authored", SecretStr("fixture"), 120, "json_object"
    )


class Model(Provider):
    def structured(self, task, data, schema):
        if task == "cached_travel_question_v1":
            self.calls.append(task)
            return dict(
                advice="合成离线问答：可以缩短天数并优先比较轻松安排。",
                citation_ids=[r["citation_id"] for r in data["references"][:1]],
                gaps=["交通仍需核实"],
                intent="MIXED",
                proposed_conditions=dict(
                    days=3 if "3天" in data["question"] else 5, driving="NO", pace="RELAXED"
                ),
            )
        if task == "planning_advisory_v4":
            self.calls.append(task)
            out = proposal(data)
            for p in out["proposals"]:
                for a in p["activities"]:
                    # Authored partial one-day choice, with gaps on other days.
                    # Also exercises a genuinely adjacent same-day map pair.
                    a["day"] = 1
            return out
        result = super().structured(task, data, schema)
        if task == "review_evidence_context_v2" and self.calls.count(task) == 2:
            for item in result["reviews"]:
                item["reference_scope"] = "AUTHOR_RECORDED_TRIP"
        return result


class GoalModel(Model):
    """Finite authored UI fixture responses, never a production interpreter."""
    def structured(self, task, data, schema):
        if task == "travel_intake_v1":
            self.followup = data["followup"]
            text = data["user_text"]
            hypothetical = text.startswith("如果")
            question = text in {"为什么推荐这些？","这个方向为什么适合？","这条路线的依据是什么？","能比较一下已有方向吗？"}
            fields = [] if hypothetical or question else [
                ("destination", "合成青谷", "合成青谷"),
                ("days", 7, "7天"), ("days", 5, "5天"),
                ("driving", "NO", "不想自驾"), ("pace", "RELAXED", "轻松一点"),
                ("driving", "YES", "想自驾"), ("transport", "SELF_DRIVE", "想自驾"),
            ]
            updates = [dict(field=k, value=v, quote=q, start=text.index(q), end=text.index(q)+len(q))
                       for k,v,q in fields if q in text and not (q=="想自驾" and "不想自驾" in text)]
            return dict(protocol="TRAVEL_INTAKE_V1", intent="HYPOTHETICAL" if hypothetical else "QUESTION" if question else "UPDATE",
                        updates=updates, summary="合成离线理解：明确陈述和假设分别处理。", user_needs=[])
        if task == "travel_supervisor_v1":
            tool = "FINISH"
            extra = dict(stop="PARTIAL")
            if data["understanding"]["intent"] in {"QUESTION","HYPOTHETICAL"}:
                tool, extra = "ANSWER", {}
            elif not data["proposed"]:
                steps=sum(r["tool"]=="RESEARCH_GAP" for r in data["previous_results"])
                if not data["followup"] and steps<2 and data["available_tools"]["RESEARCH_GAP"]["allowed"]:
                    gap=data["research_gaps"][0]["key"]
                    tool, extra = "RESEARCH_GAP", dict(query=data["destination"]+" 玩法参考 "+str(steps),gap_key=gap)
                elif data["available_tools"]["GENERATE"]["allowed"]:
                    tool, extra = "GENERATE", {}
            return dict(protocol="TRAVEL_SUPERVISOR_V1",tool=tool,reason="合成工具反馈驱动决策。",**extra)
        return super().structured(task,data,schema)


class Reader:
    text_first = False

    def __init__(self):
        self.calls = []
        self.prefix = uuid4().hex[:10]

    def connect(self):
        self.calls.append("CONNECT")

    def search(self, query):
        self.calls.append("SEARCH")
        return tuple(
            Candidate(
                "xhs:" + (self.prefix + str(i) * 24)[:24],
                "合成青谷游玩路线" + str(i),
                "normal",
                True,
            )
            for i in (1, 2)
        )

    def detail(self, candidate, number):
        self.calls.append("DETAIL")
        from datetime import datetime, timezone

        text = (
            BODY
            if number == 1
            else "合成青谷市区一日游计划，还没出发。\n城市活动草案。\nDay1：合成南园→合成北馆。\n我想了解展馆的建筑风格。\n接驳班车每天十点发车。"
        )
        return DetailMaterial(
            candidate.source_id,
            candidate.title,
            text,
            "PARTIAL_TEXT",
            datetime.now(timezone.utc).isoformat(),
        )


def research(model, reader):
    extract, review = dispatches(model)
    return lambda path, jid: run_job(
        path,
        jid,
        reader=reader,
        provider=model,
        extract_dispatch=extract,
        review_dispatch=review,
        product=True,
    )


def planning(model):
    return lambda path, jid: run_worker(path, jid, model)
