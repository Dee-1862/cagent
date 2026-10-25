"""Rules as data: stored percolator queries answer "which rule governs this instruction" with no model."""

import asyncio
import json

import httpx

from unstep import scenario
from unstep.ground import elastic_agents as ea
from unstep.ground.mock_agents import propose
from unstep.ground.rules import ElasticRules, LocalRules, RuleHit, describe, load_rules, rule_doc, rule_query


def test_the_rule_file_is_honest_about_what_has_been_reviewed():
    rules = load_rules()
    assert {r["status"] for r in rules} <= {"reviewed", "candidate", "needs_review"}
    for r in rules:
        assert r["phrases"] and (r["paragraph"] or r["status"] == "needs_review")  # no paragraph, no claim
    assert not any(r["status"] == "reviewed" for r in rules)  # nobody has read the paragraphs yet


def test_local_rules_match_spoken_forms_and_return_microsecond_timings():
    local = LocalRules()
    hits = local.match("Cessna one two three, hold short runway three three")
    assert [h.rule_id for h in hits] == ["hold-short"] and hits[0].paragraph == "3-7-2"
    assert [h.rule_id for h in local.match("Tower says we are holding short")] == ["hold-short"]
    assert local.match("N123AB cleared for takeoff")[0].status == "candidate"  # found by search, not yet read
    assert local.match("N123AB go around")[0].paragraph is None  # a rule with no paragraph claims none
    assert local.match("nothing to see here") == []
    assert hits[0].took_ms < 50


def test_the_stored_query_is_what_elastic_gets():
    q = rule_query({"phrases": ["hold short", "holding short"]})
    assert q["bool"]["minimum_should_match"] == 1
    assert [c["match_phrase"]["text"] for c in q["bool"]["should"]] == ["hold short", "holding short"]
    doc = rule_doc(load_rules()[0])
    assert set(doc) == {"query", "paragraph", "title", "status", "evidence"}


def test_the_card_never_calls_an_unreviewed_rule_reviewed():
    cand = RuleHit("hold-short", "3-7-4", "Runway Proximity", "candidate", "local", 0.02, 0.02)
    assert describe(cand).startswith("Candidate rule, not yet reviewed: FAA JO 7110.65, paragraph 3-7-4")
    done = RuleHit("hold-short", "3-7-4", "Runway Proximity", "reviewed", "elastic", 1.0, 12.0)
    assert describe(done).startswith("FAA JO 7110.65, paragraph 3-7-4 (Runway Proximity), matched in 1.0 ms")
    assert describe(RuleHit("x", None, None, "needs_review", "local", 0, 0)) is None and describe(None) is None


def elastic(handler):
    return ElasticRules("https://es.example", "key", transport=httpx.MockTransport(handler))


def test_elastic_rules_percolate_the_instruction_and_report_its_own_time():
    seen = {}

    def handler(request):
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, json={"took": 3, "hits": {"hits": [
            {"_id": "hold-short", "_source": {"paragraph": "3-7-4", "title": "Runway Proximity",
                                              "status": "candidate"}}]}})

    hits = asyncio.run(elastic(handler).match("hold short runway 33"))
    assert seen["path"] == "/unstep-rules/_search"
    assert seen["body"]["query"]["percolate"]["document"] == {"text": "hold short runway 33"}
    assert hits[0].rule_id == "hold-short" and hits[0].took_ms == 3.0 and hits[0].backend == "elastic"
    assert asyncio.run(elastic(lambda r: httpx.Response(500)).match("x")) == []


def agents(handler):
    return ea.ElasticAgents("https://kb.example", "https://es.example", "key", wait_s=1, poll_s=0.01,
                            transport=httpx.MockTransport(handler))


def stored_rule_response(paragraph="3-7-9", title="Edited in Elastic", status="reviewed"):
    return {"took": 1, "hits": {"hits": [{"_id": "hold-short", "_source": {
        "query": {"bool": {"should": [{"match_phrase": {"text": "hold short"}}], "minimum_should_match": 1}},
        "paragraph": paragraph, "title": title, "status": status, "evidence": "edited"}}]}}


def test_the_hub_answers_from_its_own_copy_and_picks_up_a_rule_edited_in_elastic():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=stored_rule_response())

    async def go():
        a = agents(handler)
        first = await a.rule_for("hold short runway 33")  # the file copy: no Elastic round trip on this path
        assert first.backend == "local" and first.paragraph == "3-7-2" and first.took_ms < 50
        await a._rules_task  # the background refresh from Elastic
        second = await a.rule_for("hold short runway 33")
        assert second.paragraph == "3-7-9" and second.status == "reviewed"  # edited in the index: no deploy
        assert calls == ["/unstep-rules/_search"]  # one refresh, not one call per instruction

    asyncio.run(go())


def test_a_failed_refresh_keeps_the_rules_the_hub_already_has():
    async def go():
        a = agents(lambda r: httpx.Response(500))
        await a.rule_for("hold short runway 33")
        await a._rules_task
        again = await a.rule_for("hold short runway 33")
        assert again.paragraph == "3-7-2"  # the file copy stands

    asyncio.run(go())


def test_the_refresh_happens_once_per_interval_not_on_every_instruction():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=stored_rule_response())

    async def go():
        a = agents(handler)
        for _ in range(5):
            await a.rule_for("hold short runway 33")
        await a._rules_task
        assert len(calls) == 1

    asyncio.run(go())


def test_the_stored_rule_goes_on_the_card_and_the_instruction_is_untouched():
    p = propose(scenario.anomaly_event(), scenario.tower_transcript())
    hit = RuleHit("hold-short", "3-7-4", "Runway Proximity", "candidate", "elastic", 2.0, 15.0)
    out = ea.with_stored_rule(p, hit)
    assert out.rule_citation.startswith("Candidate rule, not yet reviewed") and out.instruction_text == p.instruction_text
    assert out.confidence == p.confidence and ea.with_stored_rule(p, None) is p
