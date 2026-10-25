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


def test_the_hub_uses_elastics_rule_and_falls_back_to_its_own_copy():
    elastic_hit = {"took": 2, "hits": {"hits": [{"_id": "hold-short", "_source": {
        "paragraph": "3-7-9", "title": "Edited in Elastic", "status": "reviewed"}}]}}
    got = asyncio.run(agents(lambda r: httpx.Response(200, json=elastic_hit)).rule_for("hold short runway 33"))
    assert got.paragraph == "3-7-9" and got.backend == "elastic"  # a rule edited in the index wins: no deploy
    down = asyncio.run(agents(lambda r: httpx.Response(500)).rule_for("hold short runway 33"))
    assert down.paragraph == "3-7-2" and down.backend == "local"


def test_a_slow_percolate_does_not_hold_the_card():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"took": 1, "hits": {"hits": []}})

    got = asyncio.run(agents(slow).rule_for("hold short runway 33", wait_s=0.05))
    assert got.backend == "local"


def test_the_stored_rule_goes_on_the_card_and_the_instruction_is_untouched():
    p = propose(scenario.anomaly_event(), scenario.tower_transcript())
    hit = RuleHit("hold-short", "3-7-4", "Runway Proximity", "candidate", "elastic", 2.0, 15.0)
    out = ea.with_stored_rule(p, hit)
    assert out.rule_citation.startswith("Candidate rule, not yet reviewed") and out.instruction_text == p.instruction_text
    assert out.confidence == p.confidence and ea.with_stored_rule(p, None) is p
