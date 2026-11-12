"""Health endpoints (FR-OBS-2).

``/health/live`` answers 200 while the process can serve requests. It touches
no database, cache or storage on purpose: a liveness probe that fails because
a dependency is down would get a healthy process restarted. Dependency checks
belong to ``/health`` (readiness), added in F2.
"""

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def live(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
