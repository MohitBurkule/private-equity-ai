"""Postgres row-level security: the second isolation layer behind the app-level tenant filters.

- Policies on every tenant table, FORCE ROW LEVEL SECURITY so the table owner is bound too.
- The app connects as a non-owner role without BYPASSRLS; roles with BYPASSRLS or superuser
  skip RLS entirely, so verify_app_role() fails startup if the app role is privileged.
- The tenant is set per transaction (set_config(..., is_local=true)), never per connection,
  so pooled connections cannot leak a previous request's tenant. No tenant set => no rows.
"""
from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

DIRECT = ["document", "fact", "portfolio_company", "kpi_observation", "audit_event", "ingest_job", "dd_request", "covenant", "deal", "holding", "eval_run", "firm_knowledge", "agent_run", "document_source", "alert", "workflow_schedule", "target", "connection", "sync_run", "rate_window", "dd_question", "deal_note", "ic_decision", "person"]
# child tables without tenant_id: visible only if their parent row is visible
CHILD = {
    "page": ("document_id", "document", "id"),
    "fact_source": ("fact_id", "fact", "id"),
    "html_unit": ("document_id", "document", "id"),
}
CURRENT = "nullif(current_setting('app.tenant_id', true), '')"


def apply_rls(engine: Engine, app_role: str | None = None) -> None:
    """Run as the table owner. Idempotent."""
    if engine.dialect.name != "postgresql":
        return
    stmts: list[str] = []
    for t in DIRECT:
        stmts += [
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS tenant_isolation ON {t}",
            (f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {CURRENT}) "
             f"WITH CHECK (tenant_id = {CURRENT})"),
        ]
    for t, (col, parent, pcol) in CHILD.items():
        cond = f"EXISTS (SELECT 1 FROM {parent} p WHERE p.{pcol} = {t}.{col})"  # parent is RLS-filtered
        stmts += [
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS tenant_isolation ON {t}",
            f"CREATE POLICY tenant_isolation ON {t} USING ({cond}) WITH CHECK ({cond})",
        ]
    if app_role:
        stmts += [
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app_role}",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_role}",
        ]
    with engine.begin() as c:
        for s in stmts:
            c.execute(text(s))


def verify_app_role(engine: Engine) -> None:
    """Refuse to run on Postgres as a role that bypasses RLS."""
    if engine.dialect.name != "postgresql":
        return
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    if row.rolsuper or row.rolbypassrls:
        raise RuntimeError("database role bypasses row-level security; use a non-privileged app role")


def install_tenant_hook(session_factory) -> None:
    """Every new transaction of a session with info['tenant_id'] gets it as a local setting."""
    @event.listens_for(session_factory, "after_begin")
    def _set_tenant(session: Session, transaction, connection):
        tenant = session.info.get("tenant_id")
        if tenant and connection.dialect.name == "postgresql":
            connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})


def bind_tenant(session: Session, tenant_id: str) -> None:
    """Call once the tenant is known (current transaction + all later ones)."""
    session.info["tenant_id"] = tenant_id
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
