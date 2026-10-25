"""3a: the card goes out at once and the Elastic agents' citation follows, except when the policy might relay
the proposal by itself, where the agents can still veto it first."""

import asyncio

from unstep import scenario
from unstep.ground import elastic_agents as ea
from unstep.live import room as room_mod
from unstep.live.room import GroundAgents


class SlowAgents:
    def __init__(self, delay, result):
        self.delay, self.result, self.waits = delay, result, []

    async def blocked_call(self, event, transcript, proposal, wait_s=None):
        self.waits.append(wait_s)
        await asyncio.sleep(self.delay)
        return self.result


def result(paragraph="3-7-2", match=True):
    return ea.AgentsResult(intercept={"match": match},
                           compliance={"paragraph": paragraph, "title": "Taxiing", "restrictive": True},
                           execution_id="exec-1", took_ms=4200.0, citation_checked=True)


def run(monkeypatch, proposal_update, agents, with_late=True):
    base = scenario.proposed_directive().model_copy(update=proposal_update)
    monkeypatch.setattr(room_mod, "propose", lambda event, transcript: base)
    sent, late = [], []

    async def go():
        async def send(m):
            sent.append((asyncio.get_event_loop().time(), m))

        g = GroundAgents(send, wait_s=0.05, elastic=agents)

        async def on_late(event_id, merged, res):
            late.append((event_id, merged, res))

        if with_late:
            g.on_late = on_late
        await g.on_message(scenario.tower_transcript())
        await g.on_message(scenario.anomaly_event())
        await asyncio.sleep(0.05)
        first = [m for _, m in sent]
        await asyncio.sleep(0.4)
        for t in list(g._tasks):
            await t
        return first

    first = asyncio.run(go())
    return first, [m for _, m in sent], late


def test_a_proposal_a_person_decides_goes_out_at_once_and_the_citation_follows(monkeypatch):
    agents = SlowAgents(0.2, result())
    first, everything, late = run(monkeypatch, {"confidence": "medium", "rule_citation": None}, agents)
    assert first and first[0].__class__.__name__ == "ProposedDirective" and first[0].rule_citation is None
    assert len(late) == 1 and late[0][1].rule_citation and "3-7-2" in late[0][1].rule_citation
    assert agents.waits == [ea.late_wait_s()]  # the late path waits longer; nothing is blocked on it
    assert late[0][1].instruction_text == first[0].instruction_text  # the instruction never changes


def test_a_proposal_the_policy_might_relay_still_waits_for_the_agents_veto(monkeypatch):
    agents = SlowAgents(0.1, result(match=False))
    first, everything, late = run(monkeypatch, {"confidence": "high"}, agents)
    proposals = [m for m in everything if m.__class__.__name__ == "ProposedDirective"]
    assert not late and agents.waits == [None]
    assert proposals[0].confidence == "low"  # Intercept said no match: the call goes to the human


def test_without_a_room_hook_the_agents_are_waited_for_as_before(monkeypatch):
    agents = SlowAgents(0.05, result())
    first, everything, late = run(monkeypatch, {"confidence": "medium"}, agents, with_late=False)
    proposals = [m for m in everything if m.__class__.__name__ == "ProposedDirective"]
    assert not late and proposals[0].rule_citation


def test_the_room_adds_the_late_citation_to_the_open_trace_without_changing_the_instruction(monkeypatch):
    from tests.test_live_join import FakeBrowser, room as make_join_room

    r = make_join_room(monkeypatch)
    proposal = scenario.proposed_directive().model_copy(update={"confidence": "medium", "rule_citation": None})

    async def go():
        await r.start()
        atc = FakeBrowser()
        await r.join("atc", atc)
        r.traces["evt-1"] = {"event_id": "evt-1", "callsign": "N123AB", "status": "needs_you", "steps": [],
                             "timings": [], "proposal": proposal.model_dump(mode="json")}
        merged = proposal.model_copy(update={"rule_citation": "FAA JO 7110.65, paragraph 3-7-2 (Taxiing)",
                                             "confidence": "low", "confidence_method": "x + Elastic agents"})
        await r._agents_cited("evt-1", merged, result())
        t = r.traces["evt-1"]
        assert t["proposal"]["rule_citation"].endswith("(Taxiing)") and t["proposal"]["confidence"] == "low"
        assert t["proposal"]["instruction_text"] == proposal.instruction_text
        step = t["steps"][-1]
        assert step["kind"] == "agents_cited" and step["data"]["workflow_ms"] == 4200.0
        assert "after the card was shown" in step["text"]
        await asyncio.sleep(0.05)
        assert any(m.get("type") == "trace" and m["trace"]["event_id"] == "evt-1" for m in atc.messages)
        await r._agents_cited("evt-1", proposal, result())  # nothing new to add: no extra step
        assert len(t["steps"]) == 1
        await r.stop()

    asyncio.run(go())
