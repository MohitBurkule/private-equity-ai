//! Port of app/audit.py: one sha256 hash chain per tenant. The payload string is hashed as stored, so it must match
//! what Python writes: keys sorted, ", " and ": " separators.

use serde_json::Value;
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};

/// Python json.dumps(sort_keys=True) layout. Non-ASCII text is not escaped (Python would write \uXXXX).
pub fn py_json(v: &Value) -> String {
    match v {
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .iter()
                .map(|k| format!("{}: {}", serde_json::to_string(k).unwrap(), py_json(&m[*k])))
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
        Value::Array(a) => format!("[{}]", a.iter().map(py_json).collect::<Vec<_>>().join(", ")),
        other => other.to_string(),
    }
}

fn digest(prev: &str, ts: &str, actor: &str, action: &str, payload: &str) -> String {
    hex::encode(Sha256::digest(
        [prev, ts, actor, action, payload].join("\x1f").as_bytes(),
    ))
}

pub async fn log_event(
    tx: &mut Transaction<'_, Postgres>,
    tenant: &str,
    actor: &str,
    action: &str,
    payload: &Value,
) -> Result<(), sqlx::Error> {
    let prev: Option<(String,)> = sqlx::query_as(
        "SELECT hash FROM audit_event WHERE tenant_id = $1 ORDER BY id DESC LIMIT 1",
    )
    .bind(tenant)
    .fetch_optional(&mut **tx)
    .await?;
    let prev = prev.map(|r| r.0).unwrap_or_else(|| "0".repeat(64));
    let ts = chrono::Utc::now()
        .format("%Y-%m-%dT%H:%M:%S%.6f+00:00")
        .to_string();
    let body = py_json(payload);
    let hash = digest(&prev, &ts, actor, action, &body);
    sqlx::query("INSERT INTO audit_event (tenant_id, ts, actor, action, payload, prev_hash, hash) VALUES ($1,$2,$3,$4,$5,$6,$7)")
        .bind(tenant)
        .bind(&ts)
        .bind(actor)
        .bind(action)
        .bind(&body)
        .bind(&prev)
        .bind(&hash)
        .execute(&mut **tx)
        .await?;
    Ok(())
}
