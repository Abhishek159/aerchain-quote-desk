"""Buyer decisions (overrides, flag resolutions) and the audit trail."""
import json
from datetime import datetime

from . import config

EMPTY = {"flags": {}, "cells": {}, "qual": {}}


def load_overrides():
    if config.OVERRIDES.exists():
        data = json.loads(config.OVERRIDES.read_text())
        return {k: data.get(k, {}) for k in EMPTY}
    return {k: {} for k in EMPTY}


def save_override(kind, key, value, note, who="buyer"):
    ov = load_overrides()
    if value is None:
        ov[kind].pop(key, None)
    else:
        ov[kind][key] = {**value, "note": note, "by": who, "at": datetime.now().isoformat(timespec="seconds")}
    config.OVERRIDES.write_text(json.dumps(ov, indent=2, ensure_ascii=False))
    audit(f"override:{kind}", {"key": key, "value": value, "note": note}, who)


def audit(event, detail, who="system"):
    with open(config.AUDIT_LOG, "a") as fh:
        fh.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "who": who,
                             "event": event, "detail": detail}, ensure_ascii=False) + "\n")


def read_audit():
    if not config.AUDIT_LOG.exists():
        return []
    return [json.loads(l) for l in config.AUDIT_LOG.read_text().splitlines() if l.strip()]
