import { useState } from "react";
import { api2, DocumentAccess as Access } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Which identities and groups a synced source lets read each document. Admin only: the admin token stays in this page and is not saved. */
export function DocumentAccess() {
  const [tenantId, setTenantId] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [access, setAccess] = useState<Access | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Page title="Document access" hint="Documents a synced source restricts to named people or groups. Documents with no access list are open to every key in the tenant and are not shown.">
      <Card>
        <CardHead title="Tenant" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!tenantId || !adminToken) return;
          setBusy(true); setErr("");
          api2.documentAccess(tenantId, adminToken).then(setAccess).catch((x) => { setAccess(null); setErr(String(x)); }).finally(() => setBusy(false));
        }}>
          <label className="text-xs text-mut">Tenant id<Input className="mt-1" value={tenantId} onChange={(e) => setTenantId(e.target.value)} /></label>
          <label className="text-xs text-mut">Admin token<Input type="password" className="mt-1" value={adminToken} onChange={(e) => setAdminToken(e.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={!tenantId || !adminToken || busy}>{busy ? "Loading" : "Load access"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {access && access.documents.length === 0 && <Empty>No document is restricted by its source.</Empty>}
      {access && access.documents.length > 0 && (
        <Card>
          <CardHead title="Restricted documents" hint={`${access.restricted} restricted`} />
          <ul className="divide-y divide-line text-sm">
            {access.documents.map((d) => (
              <li key={d.document_id} className="space-y-2 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span>{d.filename}</span>
                  <Badge tone="mut">{d.connector}</Badge>
                  {d.deal && <Badge tone="acc">{d.deal}</Badge>}
                </div>
                <div className="flex flex-wrap gap-1">{d.grants.map((g) => <Badge key={g} tone={g.startsWith("group:") ? "warn" : "ok"}>{g}</Badge>)}</div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
