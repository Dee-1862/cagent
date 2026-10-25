"""Hybrid search of the FAA order for the card's closest rule: no model in the loop, honest about what it is."""

import asyncio
import json

import httpx

from unstep import scenario
from unstep.ground import elastic_agents as ea
from unstep.ground.mock_agents import propose


def agents(handler):
    return ea.ElasticAgents("https://kb.example", "https://es.example", "key", wait_s=1, poll_s=0.01,
                            transport=httpx.MockTransport(handler))


def hit(paragraph="3-7-2", score=0.91, title="Taxi and Ground Movement Operations"):
    return {"hits": {"hits": [{"_id": paragraph, "_score": score,
                               "_source": {"paragraph": paragraph, "title": title, "chapter": "3"}}]}}


def test_the_search_body_fuses_keyword_and_semantic_results_then_reranks():
    body = ea.faa_search_body("hold short runway 33", ".jina-reranker-v3")
    rerank = body["retriever"]["text_similarity_reranker"]
    assert rerank["inference_id"] == ".jina-reranker-v3" and rerank["field"] == "body"
    kinds = [list(r["standard"]["query"])[0] for r in rerank["retriever"]["rrf"]["retrievers"]]
    assert kinds == ["multi_match", "semantic"]
    plain = ea.faa_search_body("x", None)
    assert "rrf" in plain["retriever"] and "text_similarity_reranker" not in plain["retriever"]


def test_cite_returns_the_closest_paragraph_with_score_and_time():
    seen = []

    def handler(request):
        seen.append((request.url.host, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=hit())

    got = asyncio.run(agents(handler).cite("Cessna 123, hold short runway 33"))
    assert got["paragraph"] == "3-7-2" and got["score"] == 0.91 and got["reranked"] is True
    assert seen[0][:2] == ("es.example", "/unstep-faa/_search")


def test_cite_falls_back_to_plain_hybrid_when_the_reranker_is_rejected():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("text_similarity_reranker" in body["retriever"])
        return httpx.Response(400, json={"error": "no such endpoint"}) if calls[-1] else httpx.Response(200, json=hit())

    got = asyncio.run(agents(handler).cite("hold short"))
    assert calls == [True, False] and got["reranked"] is False


def test_cite_gives_nothing_on_errors_timeouts_and_odd_ids():
    assert asyncio.run(agents(lambda r: httpx.Response(500)).cite("x")) is None
    assert asyncio.run(agents(lambda r: httpx.Response(200, json=hit(paragraph="not-a-paragraph"))).cite("x")) is None

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=hit())

    assert asyncio.run(agents(slow).cite("x", wait_s=0.05)) is None


def test_the_card_shows_the_hit_as_a_search_result_and_leaves_the_instruction_alone():
    p = propose(scenario.anomaly_event(), scenario.tower_transcript())
    hit_ = {"paragraph": "3-7-2", "title": "Taxi", "score": 0.91, "reranked": True, "ms": 180.0}
    out = ea.with_closest_rule(p, hit_)
    assert out.rule_citation.startswith("Closest FAA rule: JO 7110.65, paragraph 3-7-2 (Taxi)")
    assert "rerank" in out.rule_citation and out.instruction_text == p.instruction_text
    assert out.confidence == p.confidence
    assert ea.with_closest_rule(p, None) is p


def test_the_one_agent_workflow_gets_the_paragraph_and_its_answer_is_split_back_into_two(monkeypatch):
    monkeypatch.setenv("UNSTEP_BLOCKED_WORKFLOW", "unstep-blocked-call-fast")
    seen = {}

    def handler(request):
        if request.url.path.startswith("/api/workflows/workflow/"):
            seen["workflow"] = request.url.path.split("/")[-2]
            seen["inputs"] = json.loads(request.content)["inputs"]
            return httpx.Response(200, json={"workflowExecutionId": "exec-9"})
        if request.url.path == "/unstep-proposals/_doc/evt-0001":
            both = {"intercept": {"match": True}, "compliance": {"paragraph": "3-7-2", "restrictive": True}}
            return httpx.Response(200, json={"found": True, "_source": {"ground": "ok " + json.dumps(both)}})
        if request.url.path == "/unstep-faa/_doc/3-7-2":
            return httpx.Response(200, json={"found": True})
        return httpx.Response(404, json={})

    rule = {"paragraph": "3-7-2", "title": "Taxi", "text": "Hold short of the runway."}
    p = propose(scenario.anomaly_event(), scenario.tower_transcript())
    result = asyncio.run(agents(handler).blocked_call(scenario.anomaly_event(), scenario.tower_transcript(), p,
                                                      rule=rule))
    assert seen["workflow"] == "unstep-blocked-call-fast" and seen["inputs"]["rule_paragraph"] == "3-7-2"
    assert seen["inputs"]["rule_text"] == "Hold short of the runway."
    assert result.intercept == {"match": True} and result.compliance["paragraph"] == "3-7-2"
    assert result.citation_checked is True


def test_the_default_is_the_parallel_pair_and_an_unknown_name_falls_back_to_it(monkeypatch):
    monkeypatch.delenv("UNSTEP_BLOCKED_WORKFLOW", raising=False)
    assert ea.blocked_call_workflow() == "parallel"
    monkeypatch.setenv("UNSTEP_BLOCKED_WORKFLOW", "something-else")
    assert ea.blocked_call_workflow() == "parallel"
    monkeypatch.setenv("UNSTEP_BLOCKED_WORKFLOW", "unstep-blocked-call")
    assert ea.blocked_call_workflow() == "unstep-blocked-call"


def test_parallel_mode_starts_both_agents_together_and_waits_for_the_slower_one(monkeypatch):
    monkeypatch.setenv("UNSTEP_BLOCKED_WORKFLOW", "parallel")
    monkeypatch.setenv("UNSTEP_INTERCEPT", "always")
    started, polls = [], {"n": 0}

    async def handler(request):
        path = request.url.path
        if path.startswith("/api/workflows/workflow/"):
            body = json.loads(request.content)["inputs"]
            started.append((path.split("/")[-2], body))
            return httpx.Response(200, json={"workflowExecutionId": "exec-" + path.split("/")[-2][-9:]})
        if path == "/unstep-proposals/_doc/evt-0001:intercept":
            return httpx.Response(200, json={"found": True, "_source": {"intercept": '{"match": true}'}})
        if path == "/unstep-proposals/_doc/evt-0001:compliance":
            polls["n"] += 1
            if polls["n"] < 4:  # the compliance agent is the slower one
                return httpx.Response(404, json={"found": False})
            return httpx.Response(200, json={"found": True, "_source": {
                "compliance": '{"paragraph": "3-7-4", "restrictive": true}'}})
        if path == "/unstep-faa/_doc/3-7-4":
            return httpx.Response(200, json={"found": True, "_source": {"body": "Hold short text"}})
        return httpx.Response(404, json={})

    p = propose(scenario.anomaly_event(), scenario.tower_transcript())
    result = asyncio.run(agents(handler).blocked_call(
        scenario.anomaly_event(), scenario.tower_transcript(), p,
        rule={"paragraph": "3-7-4", "title": "Runway Proximity"}))
    names = {n for n, _ in started}
    assert names == {"unstep-blocked-intercept", "unstep-blocked-compliance"}
    compliance_in = dict(started)["unstep-blocked-compliance"]
    assert compliance_in["rule_paragraph"] == "3-7-4" and compliance_in["rule_text"] == "Hold short text"
    assert "rule_paragraph" not in dict(started)["unstep-blocked-intercept"]
    assert result.intercept == {"match": True} and result.compliance["paragraph"] == "3-7-4"
    assert set(result.branches) == {"intercept", "compliance"} and result.citation_checked is True
    assert result.branches["compliance"] >= result.branches["intercept"]


def test_parallel_mode_keeps_one_answer_if_the_other_never_comes(monkeypatch):
    monkeypatch.setenv("UNSTEP_BLOCKED_WORKFLOW", "parallel")
    monkeypatch.setenv("UNSTEP_INTERCEPT", "always")

    def handler(request):
        path = request.url.path
        if path.startswith("/api/workflows/workflow/"):
            return httpx.Response(200, json={"workflowExecutionId": "e"})
        if path.endswith(":intercept"):
            return httpx.Response(200, json={"found": True, "_source": {"intercept": '{"match": false}'}})
        return httpx.Response(404, json={"found": False})

    p = propose(scenario.anomaly_event(), scenario.tower_transcript())
    a = agents(handler)
    a.wait_s = 0.1
    result = asyncio.run(a.blocked_call(scenario.anomaly_event(), scenario.tower_transcript(), p))
    assert result.intercept == {"match": False} and result.compliance is None and set(result.branches) == {"intercept"}
    assert ea.merge(p, result).confidence == "low"  # the veto still counts when only Intercept answered


def parallel_handler(started):
    def handler(request):
        path = request.url.path
        if path.startswith("/api/workflows/workflow/"):
            started.append(path.split("/")[-2])
            return httpx.Response(200, json={"workflowExecutionId": "exec-" + str(len(started))})
        if path.endswith(":intercept"):
            return httpx.Response(200, json={"found": True, "_source": {"intercept": '{"match": true}'}})
        if path.endswith(":compliance"):
            return httpx.Response(200, json={"found": True, "_source": {
                "compliance": '{"paragraph": "3-7-2", "restrictive": true}'}})
        if path == "/unstep-faa/_doc/3-7-2":
            return httpx.Response(200, json={"found": True, "_source": {"body": "Hold short text"}})
        return httpx.Response(404, json={})
    return handler


def run_call(a, confidence):
    p = propose(scenario.anomaly_event(), scenario.tower_transcript()).model_copy(update={"confidence": confidence})
    return asyncio.run(a.blocked_call(scenario.anomaly_event(), scenario.tower_transcript(), p,
                                      rule={"paragraph": "3-7-2", "title": "Taxi"}))


def test_intercept_is_only_asked_when_the_local_match_is_not_already_high_confidence(monkeypatch):
    monkeypatch.setenv("UNSTEP_BLOCKED_WORKFLOW", "parallel")
    monkeypatch.delenv("UNSTEP_INTERCEPT", raising=False)
    started = []
    high = run_call(agents(parallel_handler(started)), "high")
    assert started == ["unstep-blocked-compliance"] and high.intercept is None
    assert any("Intercept agent skipped" in n for n in high.notes)
    started.clear()
    run_call(agents(parallel_handler(started)), "medium")
    assert set(started) == {"unstep-blocked-intercept", "unstep-blocked-compliance"}
    monkeypatch.setenv("UNSTEP_INTERCEPT", "never")
    started.clear()
    run_call(agents(parallel_handler(started)), "medium")
    assert started == ["unstep-blocked-compliance"]
    monkeypatch.setenv("UNSTEP_INTERCEPT", "nonsense")
    assert ea.intercept_mode() == "auto"


def test_the_compliance_cache_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("UNSTEP_COMPLIANCE_CACHE_S", raising=False)
    assert ea.compliance_cache_ttl_s() == 0


def test_the_same_instruction_against_the_same_paragraph_reuses_the_compliance_answer(monkeypatch):
    monkeypatch.setenv("UNSTEP_COMPLIANCE_CACHE_S", "3600")
    monkeypatch.setenv("UNSTEP_BLOCKED_WORKFLOW", "parallel")
    monkeypatch.setenv("UNSTEP_INTERCEPT", "never")
    started = []
    a = agents(parallel_handler(started))
    first = run_call(a, "medium")
    second = run_call(a, "medium")
    assert started == ["unstep-blocked-compliance"]  # the second call started nothing
    assert second.compliance == first.compliance and second.branches["compliance"] == 0.0
    assert any("reused" in n for n in second.notes) and second.citation_checked is True
    monkeypatch.setenv("UNSTEP_COMPLIANCE_CACHE_S", "0")
    run_call(a, "medium")
    assert started == ["unstep-blocked-compliance", "unstep-blocked-compliance"]  # cache off: asks again
    other = a._cached_compliance(("hold position", None, "3-7-2"))
    assert other is None  # a different instruction is never answered from this entry
