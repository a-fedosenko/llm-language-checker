"""The demo stand: the real pipeline, one step at a time.

What makes this honest is what it does *not* contain. There is no second walk of
the ladder here -- `ladder_steps` is the one traversal (convention 11), and this
module only holds the generator open between HTTP calls and decides when to
advance it. If the demo and a scan ever disagreed about what the method does,
the demo would be a lie told in the project's own voice.

Sessions live in memory, keyed by id. A generator cannot be pickled and there is
no second user to share them with, so that is the whole of the storage design:
they die with the process, which is the correct lifetime for something a person
is watching.

**A session spends real money** -- roughly 9 to 15 calls for one language -- so
starting one is gated exactly like `POST /scans`.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from llmlc.probe.corpus import Corpus
from llmlc.probe.ladder import Step, ladder_steps
from llmlc.probe.specs import Spec, load_specs

#: How many sessions may exist at once. Low on purpose: each one holds an open
#: corpus file and an unfinished generator, and a person can watch one.
MAX_SESSIONS = 4

#: A session nobody has advanced for this long is abandoned -- a closed tab, not
#: a decision -- and is reaped so its corpus file is not left open forever.
IDLE_TIMEOUT_S = 60 * 60


@dataclass
class Session:
    id: str
    engine: str
    tag: str
    mode: str
    specs_modified: bool
    created_at: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)
    steps: list[dict] = field(default_factory=list)
    status: str = "running"          # running | done | failed | abandoned
    error: str | None = None
    #: Whether the result actually reached the database. Recorded rather than
    #: inferred: "specs were not edited" is the *policy*, and a save can still
    #: fail. A page that says "saved" on the strength of the policy is claiming
    #: something it did not check.
    persisted: bool = False
    result: dict | None = None
    corpus: Corpus | None = None
    #: What this run will ask for, worked out before anything is spent.
    plan: dict = field(default_factory=dict)
    _gen: object = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def public(self) -> dict:
        return {
            "id": self.id, "engine": self.engine, "tag": self.tag, "mode": self.mode,
            "status": self.status, "error": self.error,
            "specs_modified": self.specs_modified,
            # Stated on every response, not buried in the start call. A run whose
            # scenario was rewritten is not comparable to anything (convention 4),
            # and the page must be able to say so wherever it shows the verdict.
            "persisted": self.persisted,
            "plan": self.plan,
            "steps": self.steps, "result": self.result,
            "corpus": str(self.corpus.path) if self.corpus else None,
        }


_SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()


def _reap() -> None:
    cutoff = time.time() - IDLE_TIMEOUT_S
    for sid, s in list(_SESSIONS.items()):
        if s.touched_at < cutoff:
            close(sid, status="abandoned")


def get(session_id: str) -> Session | None:
    return _SESSIONS.get(session_id)


def listing() -> list[dict]:
    return [{"id": s.id, "engine": s.engine, "tag": s.tag, "status": s.status,
             "steps": len(s.steps)} for s in _SESSIONS.values()]


def specs_for(overrides: list[dict] | None) -> tuple[list[Spec], bool]:
    """The content specifications, with any the caller rewrote.

    Editing a scenario or its facts changes the measurement, so the fact that it
    happened is returned alongside and travels with the session. The shipped
    specs are deliberately mundane -- a memorised encyclopedia opening cannot
    satisfy "an old man bought fish and the price had doubled" -- and a rewrite
    can lose that property without anyone noticing.
    """
    shipped = load_specs()
    if not overrides:
        return shipped, False
    by_id = {s.id: s for s in shipped}
    out, modified = [], False
    for row in overrides:
        spec = Spec(id=str(row.get("id") or f"custom-{len(out)}"),
                    scenario=str(row.get("scenario") or ""),
                    facts=[str(f) for f in (row.get("facts") or []) if str(f).strip()])
        original = by_id.get(spec.id)
        if original is None or original.scenario != spec.scenario \
                or original.facts != spec.facts:
            modified = True
        out.append(spec)
    return (out or shipped), modified


def plan_for(scheme, tag: str) -> dict:
    """What the run will actually ask the model for, before it asks.

    This exists because two tags can be the same experiment and nothing said so.
    `sr-RS-Cyrl` and `sr-ME-Cyrl` share an equivalence class and produce the
    identical prompt -- "Serbian (Cyrillic script)" -- so running both looks
    like two measurements and is one, repeated. That is the documented design
    (protocol 010 measured country-qualified designators and rejected them; the
    variant distinction is meant to come from marker sets, which exist for 2 of
    534 variant tags), but a design you can only discover by running the same
    thing twice and noticing is not a design anyone can check.
    """
    from llmlc.probe import designator as dsg
    from llmlc.probe.variant import is_script_variant

    lang = scheme.get(tag)
    if lang is None:
        return {}
    candidates = dsg.candidates(lang, qualify_script=is_script_variant(scheme, lang) or None)
    primary = candidates[0].value if candidates else ""
    siblings = scheme.variants_of(tag)
    # Subtags the designator does not name. The region is the usual one, and it
    # is the whole of the difference between Serbian as written in Belgrade and
    # in Podgorica.
    unnamed = [part for part, value in (("region", lang.region),)
               if value and value.lower() not in primary.lower()
               and (lang.name or "").lower() != primary.lower()]
    return {
        "tag": tag,
        "cls": lang.cls,
        "designators": [c.value for c in candidates],
        "primary": primary,
        "siblings": siblings,
        "unnamed_subtags": unnamed,
        "region": lang.region,
    }


def start(*, engine: str, tag: str, scheme, client, backtranslators, judge_model: str,
          pivot: str, mode: str, specs: list[Spec], specs_modified: bool,
          cache=None, sweep_all: bool = False) -> Session:
    with _LOCK:
        _reap()
        live = [s for s in _SESSIONS.values() if s.status == "running"]
        if len(live) >= MAX_SESSIONS:
            raise RuntimeError(
                f"{len(live)} demo session(s) already open, which is the limit. "
                f"Finish or close one first.")
        sid = uuid.uuid4().hex[:12]
        corpus = Corpus()
        session = Session(id=sid, engine=engine, tag=tag, mode=mode,
                          specs_modified=specs_modified, corpus=corpus,
                          plan=plan_for(scheme, tag))
        session._gen = ladder_steps(
            scheme=scheme, tag=tag, engine=engine, client=client,
            backtranslators=backtranslators, judge_model=judge_model,
            specs=specs, corpus=corpus, pivot=pivot, sweep_all=sweep_all,
            cache=cache)
        _SESSIONS[sid] = session
        return session


def advance(session: Session, *, on_result=None) -> dict | None:
    """Take one step. Returns the step, or None when the run is over.

    Serialised per session: a generator advanced from two threads at once would
    interleave, and FastAPI runs sync endpoints in a threadpool.
    """
    with session._lock:
        if session.status != "running":
            return None
        session.touched_at = time.time()
        try:
            step: Step = next(session._gen)
        except StopIteration as done:
            session.status = "done"
            _finish(session, done.value, on_result=on_result)
            return None
        except Exception as e:  # noqa: BLE001 -- surfaced to the page, not swallowed
            session.status = "failed"
            session.error = f"{type(e).__name__}: {e}"
            _close_corpus(session)
            return None
        payload = step.as_dict()
        session.steps.append(payload)
        if step.terminal:
            # The generator has nothing left but its return value, and asking for
            # it costs nothing. Collecting it here means the terminal step and
            # the verdict arrive together, instead of making the reader click
            # once more for a step that does not exist.
            try:
                next(session._gen)
            except StopIteration as done:
                session.status = "done"
                _finish(session, done.value, on_result=on_result)
            except Exception as e:  # noqa: BLE001
                session.status = "failed"
                session.error = f"{type(e).__name__}: {e}"
                _close_corpus(session)
        return payload


def _finish(session: Session, result, *, on_result=None) -> None:
    session.result = {
        "tag": result.tag, "engine": result.engine,
        "designator": result.designator,
        "backtranslator": result.backtranslator, "judge": result.judge_model,
        "pivot": result.pivot, "rungs_run": result.rungs_run,
        "calls": dict(result.calls), "score": result.score.as_dict(),
        "workflow": result.score.workflow,
    }
    _close_corpus(session)
    # A run whose specs were rewritten is not a measurement of anything the rest
    # of the table can be compared against, so it stays out of the results.
    # The corpus keeps it either way, which is where you look at the text.
    if not session.specs_modified and on_result is not None:
        try:
            on_result(result)
            session.persisted = True
        except Exception as e:  # noqa: BLE001
            session.error = f"result not saved: {type(e).__name__}: {e}"


def _close_corpus(session: Session) -> None:
    try:
        if session.corpus is not None:
            session.corpus.close()
    except Exception:  # noqa: BLE001 -- closing a file is not worth failing a run over
        pass


def close(session_id: str, *, status: str = "abandoned") -> bool:
    session = _SESSIONS.pop(session_id, None)
    if session is None:
        return False
    if session.status == "running":
        session.status = status
        gen = session._gen
        if gen is not None and hasattr(gen, "close"):
            gen.close()          # every yield sits after its work: nothing half-paid
    _close_corpus(session)
    return True


def reset_for_tests() -> None:
    for sid in list(_SESSIONS):
        close(sid)
