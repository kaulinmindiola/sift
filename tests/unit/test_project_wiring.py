"""Checks that the project-level wiring keeps the guarantees the design relies on."""


def test_celery_acknowledges_late_and_requeues_lost_tasks() -> None:
    from sift import celery_app

    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_default_queue == "imports"
    assert conf.accept_content == ["json"]


def test_asgi_application_routes_http() -> None:
    from channels.routing import ProtocolTypeRouter

    from sift.asgi import application

    assert isinstance(application, ProtocolTypeRouter)
    assert set(application.application_mapping) == {"http"}
