"""Run the gateway: python -m ground.gateway"""

import logging

import uvicorn

from ground.gateway.app import create_app
from ground.gateway.config import Settings
from ground.gateway.sinks import ElasticSink, JsonlSink
from ground.gateway.workflow import HttpWorkflowTrigger, NoopTrigger


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings.from_env()
    log = logging.getLogger("unstep.gateway")

    if settings.elastic_url and settings.elastic_api_key:
        sink = ElasticSink(settings.elastic_url, settings.elastic_api_key, settings.elastic_events_index)
        log.info("storing events in Elastic index %s", settings.elastic_events_index)
    else:
        sink = JsonlSink(settings.events_path)
        log.info("Elastic not configured, storing events in %s", settings.events_path)

    if settings.elastic_workflow_url and settings.elastic_api_key:
        trigger = HttpWorkflowTrigger(settings.elastic_workflow_url, settings.elastic_api_key)
    else:
        trigger = NoopTrigger()
        log.info("Workflow not configured, AnomalyEvents will not trigger agents")

    app = create_app(sink, trigger, voice_controller_id=settings.voice_controller_id)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
