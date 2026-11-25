"""Per-operation cache for one Save / Fetch / Calculate / Submit.

The same attendance arithmetic used to be redone several times per employee (snapshot,
calculation, fingerprint, Payroll's onchange) and the late-login rules re-read the whole
month for every late day. Inside a `payroll_scope()` those results are computed once and
reused; outside one (every other feature) nothing is cached. The scope ends with the
operation, so a later click always reads fresh data."""
import copy
import threading
from contextlib import contextmanager
from functools import wraps

_local = threading.local()


def scope_cache():
    """The active per-operation dict, or None outside a payroll operation."""
    return getattr(_local, 'cache', None)


@contextmanager
def payroll_scope():
    owner = not hasattr(_local, 'cache')
    if owner:
        _local.cache = {}
    try:
        yield
    finally:
        if owner:
            _local.__dict__.pop('cache', None)


def scoped(method):
    """Decorator: run an entry-point method inside payroll_scope()."""
    @wraps(method)
    def wrapper(*args, **kwargs):
        with payroll_scope():
            return method(*args, **kwargs)
    return wrapper


def cached(key, compute):
    """compute() once per operation for key; callers get a private deep copy."""
    cache = scope_cache()
    if cache is None:
        return compute()
    if key not in cache:
        cache[key] = compute()
    return copy.deepcopy(cache[key])
