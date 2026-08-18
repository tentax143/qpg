"""
Management command: python manage.py celery_health

Answers the one question that is otherwise invisible: **is every queue actually being
consumed?**

A worker that isn't running does not raise anything. Django keeps accepting requests,
`.delay()` keeps succeeding, the row keeps saying 'queued' — and the teacher just sees a
screen that loads forever. That is the same symptom as a slow LLM, a full queue and a dead
broker, which is why it went undiagnosed. This command separates them in one shot.

Run it after starting the stack, and any time someone reports "it's just loading".

    python manage.py celery_health

Exit code is 1 when something is actually wrong, so it can be used as a check in a script.
"""

import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ExamPattern, QuestionPaper


# Every queue the app publishes to, and what stops working when nobody drains it.
# Keep in sync with CELERY_TASK_ROUTES / CELERY_TASK_DEFAULT_QUEUE in settings.
QUEUES = {
    "celery":   "paper generation, material ingest, enrichment, answer keys",
    "patterns": "AI pattern generation and PDF pattern import",
}


class Command(BaseCommand):
    help = "Check that a Celery worker is consuming every queue, and report stuck jobs."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=float, default=3.0,
                            help="Seconds to wait for workers to answer the ping (default 3).")
        parser.add_argument("--check-keys", action="store_true",
                            help="Actually call the LLM endpoint once per API key. A revoked key "
                                 "is otherwise silent: converse() fails over to a sibling, so "
                                 "everything still works while half the calls waste a round trip "
                                 "and single-retry call sites hard-fail.")

    def handle(self, *args, **opts):
        ok = True

        # ── Broker ────────────────────────────────────────────────────────────────
        depths = {}
        try:
            import redis
            from urllib.parse import urlparse
            u = urlparse(settings.CELERY_BROKER_URL)
            r = redis.Redis(host=u.hostname or "127.0.0.1", port=u.port or 6379,
                            db=int((u.path or "/0").lstrip("/") or 0),
                            socket_connect_timeout=3)
            r.ping()
            self.stdout.write(self.style.SUCCESS(
                f"broker   OK   {settings.CELERY_BROKER_URL}"))
            for q in QUEUES:
                depths[q] = r.llen(q)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f"broker   DEAD  {settings.CELERY_BROKER_URL} — {type(exc).__name__}: {exc}"))
            self.stdout.write("         Nothing can run. Start Redis (see run_commands.txt).")
            return self._exit(False)

        # ── Workers ───────────────────────────────────────────────────────────────
        from qpg.celery import app
        inspect = app.control.inspect(timeout=opts["timeout"])
        try:
            pong = inspect.ping() or {}
            consumed = inspect.active_queues() or {}
            active = inspect.active() or {}
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"workers  ERROR while inspecting: {exc}"))
            return self._exit(False)

        if not pong:
            self.stdout.write(self.style.ERROR("workers  NONE responding"))
            ok = False
        else:
            self.stdout.write(self.style.SUCCESS(f"workers  {len(pong)} responding"))
            for name in sorted(pong):
                queues = [q["name"] for q in consumed.get(name, [])]
                running = [t["name"].rsplit(".", 1)[-1] for t in active.get(name, [])]
                self.stdout.write(
                    f"         {name}\n"
                    f"           consumes : {', '.join(queues) or '(nothing!)'}\n"
                    f"           running  : {', '.join(running) or 'idle'}")

        # ── The actual check: is every queue covered? ─────────────────────────────
        self.stdout.write("")
        covered = {q for qs in consumed.values() for q in [x["name"] for x in qs]}
        for q, what in QUEUES.items():
            depth = depths.get(q, 0)
            if q in covered:
                self.stdout.write(self.style.SUCCESS(
                    f"queue    OK    {q:9s} waiting={depth}   ({what})"))
            else:
                ok = False
                self.stdout.write(self.style.ERROR(
                    f"queue    ORPHAN {q:9s} waiting={depth}   ({what})"))
                self.stdout.write(self.style.ERROR(
                    f"         >> NOBODY is consuming '{q}'. Anything queued here will "
                    f"NEVER run and the UI will just spin.\n"
                    f"         >> Start the missing worker — see run_commands.txt."))

        # ── Stuck rows, so a wedged job is named rather than guessed at ───────────
        now = timezone.now()
        stuck_papers = [
            p for p in QuestionPaper.objects.filter(status__in=["queued", "generating"])
            if (now - p.updated_at).total_seconds() > 15 * 60]
        stuck_patterns = [
            p for p in ExamPattern.objects.filter(status__in=["queued", "generating"])
            if (now - p.updated_at).total_seconds() > 10 * 60]

        self.stdout.write("")
        if not stuck_papers and not stuck_patterns:
            self.stdout.write(self.style.SUCCESS("jobs     OK    nothing stuck"))
        for p in stuck_papers:
            mins = (now - p.updated_at).total_seconds() / 60
            self.stdout.write(self.style.WARNING(
                f"jobs     STUCK paper #{p.id} '{p.status}' for {mins:.0f} min "
                f"({p.class_name} {p.subject}, by {p.created_by})"))
        for p in stuck_patterns:
            mins = (now - p.updated_at).total_seconds() / 60
            self.stdout.write(self.style.WARNING(
                f"jobs     STUCK pattern #{p.id} '{p.status}' for {mins:.0f} min "
                f"({p.class_name} {p.subject}, by {p.created_by})"))
        if stuck_papers or stuck_patterns:
            self.stdout.write(
                "         Stale rows are auto-failed on the next dashboard/pattern poll "
                "(reap_stale_papers / reap_stale_patterns) so queue slots are freed.")

        # ── API keys: a dead key is silent but doubles latency and can hard-fail ──
        from core import mantle_client
        self.stdout.write("")
        n = mantle_client.num_keys()
        if n == 0:
            ok = False
            self.stdout.write(self.style.ERROR("keys     NONE configured — no generation can work"))
        else:
            self.stdout.write(f"keys     {mantle_client.keys_summary()}")
            if not opts["check_keys"]:
                self.stdout.write("         (add --check-keys to actually call each one)")
            else:
                import requests
                url = f"{mantle_client.BASE_URL}/chat/completions"
                for key in mantle_client._get_keys():
                    label = mantle_client._key_label(key)
                    try:
                        resp = requests.post(
                            url,
                            headers={"Content-Type": "application/json",
                                     "Authorization": f"Bearer {key}"},
                            json={"model": mantle_client.GEN_MODEL,
                                  "messages": [{"role": "user", "content": "ping"}],
                                  "max_tokens": 5},
                            timeout=(10, 30))
                        if resp.ok:
                            self.stdout.write(self.style.SUCCESS(
                                f"         key {label} OK (HTTP {resp.status_code})"))
                        else:
                            ok = False
                            self.stdout.write(self.style.ERROR(
                                f"         key {label} HTTP {resp.status_code} "
                                f"{resp.text[:100]} -- rotate this key in .env"))
                    except Exception as exc:
                        ok = False
                        self.stdout.write(self.style.ERROR(
                            f"         key {label} {type(exc).__name__}: {exc}"))

        return self._exit(ok)

    def _exit(self, ok):
        self.stdout.write("")
        if ok:
            self.stdout.write(self.style.SUCCESS("RESULT   healthy"))
        else:
            self.stdout.write(self.style.ERROR("RESULT   PROBLEMS FOUND (see above)"))
            sys.exit(1)
