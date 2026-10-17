//! Port of the deal wall and source ACL (app/acl.py): which documents a principal may see.
//! Decided in the app layer on top of tenant RLS, as in FastAPI. Rules:
//! - a deal scope (keys with `deals`) sees only documents tagged with one of those deals (untagged fail closed);
//! - an MNPI deal is hidden unless the key is scoped to it by name or created it;
//! - a document whose synced source access list names nobody this key matches is hidden.

use crate::auth::Principal;
use crate::error::ApiError;
use serde_json::Value;
use sqlx::{Postgres, Transaction};
use std::collections::HashSet;

pub struct Visibility {
    /// Python `deals`: None means unrestricted inside the tenant.
    deal_scope: Option<HashSet<String>>,
    /// MNPI deals this key may not see.
    hidden_deals: HashSet<String>,
    /// MNPI deals this key may see (for the mnpi_access audit trail).
    pub visible_mnpi: HashSet<String>,
    /// Documents whose synced access list excludes this principal.
    hidden_docs: HashSet<String>,
    /// Python visible_doc_ids: None when nothing narrows the tenant.
    scope: Option<HashSet<String>>,
}

impl Visibility {
    pub async fn load(tx: &mut Transaction<'_, Postgres>, p: &Principal) -> Result<Self, ApiError> {
        let mnpi: Vec<(String, String)> =
            sqlx::query_as("SELECT name, created_by FROM deal WHERE mnpi")
                .fetch_all(&mut **tx)
                .await?;
        let mut hidden_deals = HashSet::new();
        let mut visible_mnpi = HashSet::new();
        for (name, created_by) in mnpi {
            // _may_see_mnpi: scoped by name, or the key that flagged the deal.
            let may = p.deal_scope_has(&name) || (!p.key_id.is_empty() && created_by == p.key_id);
            if may {
                visible_mnpi.insert(name);
            } else {
                hidden_deals.insert(name);
            }
        }

        let grants = p.grants();
        let acls: Vec<(String, String)> =
            sqlx::query_as("SELECT document_id, acl FROM document_source WHERE acl IS NOT NULL")
                .fetch_all(&mut **tx)
                .await?;
        let mut hidden_docs = HashSet::new();
        for (doc_id, acl) in acls {
            // A key with no identity or groups matches nothing, so restricted documents fail closed.
            let allowed: HashSet<String> = match serde_json::from_str::<Value>(&acl) {
                Ok(Value::Array(a)) => a
                    .into_iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect(),
                _ => HashSet::new(),
            };
            if grants.is_disjoint(&allowed) {
                hidden_docs.insert(doc_id);
            }
        }

        let mut vis = Self {
            deal_scope: p.deals.clone(),
            hidden_deals,
            visible_mnpi,
            hidden_docs,
            scope: None,
        };
        // Python: None when the deal scope and the ACL narrow nothing.
        if vis.deal_scope.is_none() && vis.hidden_deals.is_empty() && vis.hidden_docs.is_empty() {
            return Ok(vis);
        }
        let docs: Vec<(String, Option<String>)> = sqlx::query_as("SELECT id, deal FROM document")
            .fetch_all(&mut **tx)
            .await?;
        vis.scope = Some(
            docs.into_iter()
                .filter(|(id, deal)| {
                    vis.deal_allows(deal.as_deref()) && !vis.hidden_docs.contains(id)
                })
                .map(|(id, _)| id)
                .collect(),
        );
        Ok(vis)
    }

    /// doc_visible's deal half: the deal scope and the MNPI wall.
    pub fn deal_allows(&self, deal: Option<&str>) -> bool {
        let in_scope = match (&self.deal_scope, deal) {
            (None, _) => true,
            (Some(scope), Some(d)) => scope.contains(d),
            (Some(_), None) => false,
        };
        in_scope && deal.is_none_or(|d| !self.hidden_deals.contains(d))
    }

    /// The source ACL half, for single-document access (_own_doc).
    pub fn acl_allows(&self, doc_id: &str) -> bool {
        !self.hidden_docs.contains(doc_id)
    }

    /// fact_visible: unrestricted facts see everything; otherwise every source document must be in scope.
    pub fn fact_visible(&self, source_doc_ids: &[&str]) -> bool {
        match &self.scope {
            None => true,
            Some(scope) => {
                !source_doc_ids.is_empty() && source_doc_ids.iter().all(|d| scope.contains(*d))
            }
        }
    }
}
