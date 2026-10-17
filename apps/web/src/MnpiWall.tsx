import { useState } from "react";
import { api2, KeyWall } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Which keys of a tenant can see which deals. Read-only: a wall change goes through the admin API, reviewed there. */
export function MnpiWall() {
  const [tenantId, setTenantId] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [keys, setKeys] = useState<KeyWall[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Page title="MNPI wall" hint="Deal access per key. Unrestricted keys see every deal, walled keys only the deals listed. The admin token stays in this page and is not saved.">
      <Card>
        <CardHead title="Tenant" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!tenantId || !adminToken) return;
          setBusy(true); setErr("");
          api2.adminKeys(tenantId, adminToken).then(setKeys).catch((x) => { setKeys(null); setErr(String(x)); }).finally(() => setBusy(false));
        }}>
          <label className="text-xs text-mut">Tenant id<Input className="mt-1" value={tenantId} onChange={(e) => setTenantId(e.target.value)} /></label>
          <label className="text-xs text-mut">Admin token<Input type="password" className="mt-1" value={adminToken} onChange={(e) => setAdminToken(e.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={!tenantId || !adminToken || busy}>{busy ? "Loading" : "Load keys"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {keys && keys.length === 0 && <Empty>No keys for this tenant.</Empty>}
      {keys && keys.length > 0 && (
        <Card>
          <CardHead title="Keys" hint={`${keys.filter((k) => k.deals === null && !k.revoked).length} unrestricted`} />
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-mut"><th className="p-3">Key</th><th>Role</th><th>Deals</th><th>Status</th></tr></thead>
            <tbody>{keys.map((k) => (
              <tr key={k.key_id} className="border-t border-line">
                <td className="p-3 font-mono text-xs">{k.key_id}</td>
                <td>{k.role}</td>
                <td>
                  {k.deals === null ? <Badge tone="warn">all deals</Badge> : k.deals.length === 0 ? <span className="text-mut">none</span> : (
                    <span className="flex flex-wrap gap-1">{k.deals.map((d) => (
                      <Badge key={d} tone="ok">{d}{k.deal_roles[d] ? `: ${k.deal_roles[d]}` : ""}</Badge>
                    ))}</span>
                  )}
                </td>
                <td>{k.revoked ? <Badge tone="bad">revoked</Badge> : <span className="text-mut">active</span>}</td>
              </tr>))}</tbody>
          </table>
        </Card>
      )}
    </Page>
  );
}
