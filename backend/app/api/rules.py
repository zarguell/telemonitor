"""Rule management + rule testing endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import ACTION_RULE_CREATE, ACTION_RULE_DELETE, ACTION_RULE_TEST, ACTION_RULE_UPDATE, log_audit
from ..db import get_db
from ..models import Rule, RuleMatch, Severity
from ..security import AuthContext, require_any, require_operator
from ..services.normalize import excerpt, normalize_text
from ..services.rules_engine import evaluate_rule, regex_safety_warning, validate_definition

router = APIRouter(prefix="/rules", tags=["rules"])

SEVERITIES = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    severity: str = Severity.MEDIUM
    definition: dict
    source_scope: list[int] | None = None
    dedup_window_seconds: int = 3600
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    severity: str | None = None
    definition: dict | None = None
    source_scope: list[int] | None = None
    dedup_window_seconds: int | None = None
    enabled: bool | None = None


class RuleTestRequest(BaseModel):
    definition: dict
    sample_text: str
    source_id: int | None = None


def _rule_dict(r: Rule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "enabled": r.enabled,
        "severity": r.severity,
        "definition": r.definition,
        "source_scope": r.source_scope,
        "dedup_window_seconds": r.dedup_window_seconds,
        "version": r.version,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "last_match_at": r.last_match_at.isoformat() if r.last_match_at else None,
    }


def _match_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(RuleMatch.rule_id, func.count(RuleMatch.id)).group_by(RuleMatch.rule_id)
    ).all()
    return {rid: cnt for rid, cnt in rows}


@router.get("")
def list_rules(ctx: AuthContext = Depends(require_any), db: Session = Depends(get_db)):
    rules = db.scalars(select(Rule).order_by(Rule.name)).all()
    counts = _match_counts(db)
    items = []
    for r in rules:
        d = _rule_dict(r)
        d["recent_match_count"] = counts.get(r.id, 0)
        items.append(d)
    return {"items": items, "total": len(items)}


@router.post("")
def create_rule(
    body: RuleCreate,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    errors = validate_definition(body.definition)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    if body.severity not in SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {SEVERITIES}")
    rule = Rule(
        name=body.name,
        description=body.description,
        severity=body.severity,
        definition=body.definition,
        source_scope=body.source_scope,
        dedup_window_seconds=max(0, body.dedup_window_seconds),
        enabled=body.enabled,
        created_by=ctx.user.id,
        updated_by=ctx.user.id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_RULE_CREATE,
        object_type="rule",
        object_id=str(rule.id),
        detail={"name": rule.name, "severity": rule.severity},
        ip_address=ctx.ip_address,
    )
    return _rule_dict(rule)


@router.patch("/{rule_id}")
def patch_rule(
    rule_id: int,
    body: RulePatch,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    changed = False
    if body.definition is not None:
        errors = validate_definition(body.definition)
        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors))
        rule.definition = body.definition
        rule.version += 1
        changed = True
    if body.name is not None:
        rule.name = body.name
        changed = True
    if body.description is not None:
        rule.description = body.description
        changed = True
    if body.severity is not None:
        if body.severity not in SEVERITIES:
            raise HTTPException(status_code=400, detail=f"severity must be one of {SEVERITIES}")
        rule.severity = body.severity
        changed = True
    if body.source_scope is not None:
        rule.source_scope = body.source_scope
        changed = True
    if body.dedup_window_seconds is not None:
        rule.dedup_window_seconds = max(0, body.dedup_window_seconds)
        changed = True
    if body.enabled is not None:
        rule.enabled = body.enabled
        changed = True
    rule.updated_by = ctx.user.id
    db.commit()
    db.refresh(rule)
    if changed:
        log_audit(
            db,
            actor_user_id=ctx.user.id,
            actor_username=ctx.user.username,
            action=ACTION_RULE_UPDATE,
            object_type="rule",
            object_id=str(rule.id),
            detail={"name": rule.name, "version": rule.version, "enabled": rule.enabled},
            ip_address=ctx.ip_address,
        )
    return _rule_dict(rule)


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    db.delete(rule)
    db.commit()
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_RULE_DELETE,
        object_type="rule",
        object_id=str(rule_id),
        detail={"name": rule.name},
        ip_address=ctx.ip_address,
    )
    return {"ok": True}


@router.post("/test")
def test_rule(
    body: RuleTestRequest,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    errors = validate_definition(body.definition)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    warning = None
    for cond in body.definition.get("conditions", []):
        if cond.get("type") == "regex":
            warning = regex_safety_warning(cond.get("value", ""))
            if warning:
                break
    from ..audit import get_setting

    aliases = (get_setting(db, "aliases", {}) or {}).get("items", []) or []
    from ..services.extractors import extract_indicators

    inds = extract_indicators(body.sample_text, aliases)
    result = evaluate_rule(
        body.definition,
        {
            "normalized_text": normalize_text(body.sample_text),
            "source_id": body.source_id,
            "indicators": inds,
        },
    )
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_RULE_TEST,
        object_type="rule",
        detail={"matched": result["matched"], "conditions": len(body.definition.get("conditions", []))},
        ip_address=ctx.ip_address,
    )
    return {
        "matched": result["matched"],
        "warning": warning,
        "conditions": result["conditions"],
        "excerpt": excerpt(body.sample_text),
        "indicators": inds,
    }
